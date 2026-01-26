#!/usr/bin/env python3
"""
P6Analyzer - Schedule Delay Analysis Tool for Oracle Primavera P6

Analyzes critical path activities to identify delays and their causes/impacts.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO format date string to datetime object."""
    if not date_str:
        return None
    # Handle both formats: with 'Z' suffix and without
    date_str = date_str.replace('Z', '+00:00')
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None


def load_activities(filepath: str) -> Tuple[Dict[str, dict], dict]:
    """
    Load activities JSON file and index by task_code.

    Returns:
        Tuple of (activities_dict indexed by task_code, project_info)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    activities = {}
    for activity in data.get('activities', []):
        task_code = activity.get('task_code')
        if task_code:
            activities[task_code] = activity

    return activities, data.get('project', {})


def load_critical_path(filepath: str) -> Tuple[Set[str], dict, dict]:
    """
    Load critical path JSON file and extract task codes.

    Returns:
        Tuple of (set of task_codes on critical path, project_info, summary)
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    critical_tasks = set()
    for path in data.get('critical_paths', []):
        for activity in path.get('activities', []):
            task_code = activity.get('task_code')
            if task_code:
                critical_tasks.add(task_code)

    return critical_tasks, data.get('project', {}), data.get('summary', {})


def calculate_delay_days(baseline_date: Optional[datetime],
                         updated_date: Optional[datetime]) -> Optional[float]:
    """
    Calculate delay in days between baseline and updated dates.

    Returns:
        Positive number if delayed, 0 if on time, negative if ahead, None if dates missing
    """
    if not baseline_date or not updated_date:
        return None

    delta = updated_date - baseline_date
    return delta.total_seconds() / (24 * 3600)  # Convert to days


def is_date_delayed(baseline_date: Optional[datetime],
                    updated_date: Optional[datetime]) -> bool:
    """Check if updated date is later than baseline date."""
    if not baseline_date or not updated_date:
        return False
    return updated_date > baseline_date


def check_predecessor_caused_delay(
    activity_task_code: str,
    baseline_activities: Dict[str, dict],
    updated_activities: Dict[str, dict]
) -> List[dict]:
    """
    Check if any predecessor's delay could have caused this activity's delay.

    Returns:
        List of predecessors that could have caused the delay
    """
    causing_predecessors = []

    updated_activity = updated_activities.get(activity_task_code)
    if not updated_activity:
        return causing_predecessors

    predecessors = updated_activity.get('dependencies', {}).get('predecessors', [])

    for pred in predecessors:
        pred_code = pred.get('task_code')
        dep_type = pred.get('dependency_type', 'FS')

        if not pred_code:
            continue

        baseline_pred = baseline_activities.get(pred_code)
        updated_pred = updated_activities.get(pred_code)

        if not baseline_pred or not updated_pred:
            continue

        # Determine which date to check based on dependency type
        if dep_type in ('FS', 'FF'):
            # Finish-based: check predecessor's end date
            baseline_date = parse_date(baseline_pred.get('planned_end_date'))
            updated_date = parse_date(updated_pred.get('planned_end_date'))
        else:  # SS, SF
            # Start-based: check predecessor's start date
            baseline_date = parse_date(baseline_pred.get('planned_start_date'))
            updated_date = parse_date(updated_pred.get('planned_start_date'))

        if is_date_delayed(baseline_date, updated_date):
            causing_predecessors.append({
                'task_code': pred_code,
                'task_name': updated_pred.get('task_name', ''),
                'dependency_type': dep_type
            })

    return causing_predecessors


def find_impacted_successors(
    activity_task_code: str,
    start_delayed: bool,
    end_delayed: bool,
    updated_activities: Dict[str, dict]
) -> List[dict]:
    """
    Find direct successors that will be impacted by this activity's delay.

    Returns:
        List of impacted successor tasks
    """
    impacted = []

    activity = updated_activities.get(activity_task_code)
    if not activity:
        return impacted

    successors = activity.get('dependencies', {}).get('successors', [])

    for succ in successors:
        succ_code = succ.get('task_code')
        dep_type = succ.get('dependency_type', 'FS')

        if not succ_code:
            continue

        # Determine if this successor is impacted based on dependency type
        is_impacted = False
        if dep_type in ('FS', 'FF') and end_delayed:
            # Finish-based dependency: impacted if this activity's end is delayed
            is_impacted = True
        elif dep_type in ('SS', 'SF') and start_delayed:
            # Start-based dependency: impacted if this activity's start is delayed
            is_impacted = True

        if is_impacted:
            succ_activity = updated_activities.get(succ_code, {})
            impacted.append({
                'task_code': succ_code,
                'task_name': succ_activity.get('task_name', ''),
                'dependency_type': dep_type
            })

    return impacted


def calculate_critical_path_impact(
    critical_tasks: Set[str],
    baseline_activities: Dict[str, dict],
    updated_activities: Dict[str, dict]
) -> Optional[dict]:
    """
    Calculate the project delay based on the terminal activity of the critical path.

    Returns:
        Dictionary with project delay info, or None if no terminal activity found
    """
    # Find the terminal activity (latest end date in updated schedule)
    terminal_activity = None
    terminal_end_date = None

    for task_code in critical_tasks:
        updated = updated_activities.get(task_code)
        if not updated:
            continue

        end_date = parse_date(updated.get('planned_end_date'))
        if end_date and (terminal_end_date is None or end_date > terminal_end_date):
            terminal_end_date = end_date
            terminal_activity = updated
            terminal_task_code = task_code

    if not terminal_activity:
        return None

    # Get baseline info for the terminal activity
    baseline = baseline_activities.get(terminal_task_code)
    if not baseline:
        return None

    baseline_end = parse_date(baseline.get('planned_end_date'))
    updated_end = parse_date(terminal_activity.get('planned_end_date'))

    delay_days = calculate_delay_days(baseline_end, updated_end)

    return {
        'project_delay_days': round(delay_days, 1) if delay_days else 0,
        'terminal_activity': {
            'task_code': terminal_task_code,
            'task_name': terminal_activity.get('task_name', ''),
            'baseline_end': baseline.get('planned_end_date'),
            'updated_end': terminal_activity.get('planned_end_date')
        }
    }


def analyze_delays(
    task_codes: Set[str],
    baseline_activities: Dict[str, dict],
    updated_activities: Dict[str, dict]
) -> List[dict]:
    """
    Analyze specified activities for delays.

    Args:
        task_codes: Set of task codes to analyze
        baseline_activities: Baseline schedule indexed by task_code
        updated_activities: Updated schedule indexed by task_code

    Returns:
        List of delayed activity analysis results
    """
    delayed_activities = []

    for task_code in task_codes:
        baseline = baseline_activities.get(task_code)
        updated = updated_activities.get(task_code)

        # Skip if activity doesn't exist in baseline (new activity)
        if not baseline:
            continue

        # Skip if activity doesn't exist in updated
        if not updated:
            continue

        # Parse dates
        baseline_start = parse_date(baseline.get('planned_start_date'))
        baseline_end = parse_date(baseline.get('planned_end_date'))
        updated_start = parse_date(updated.get('planned_start_date'))
        updated_end = parse_date(updated.get('planned_end_date'))

        # Check for delays
        start_delayed = is_date_delayed(baseline_start, updated_start)
        end_delayed = is_date_delayed(baseline_end, updated_end)

        if not start_delayed and not end_delayed:
            continue

        # Calculate delay amounts
        start_delay_days = calculate_delay_days(baseline_start, updated_start)
        end_delay_days = calculate_delay_days(baseline_end, updated_end)

        # Analyze cause (predecessors)
        causing_predecessors = check_predecessor_caused_delay(
            task_code, baseline_activities, updated_activities
        )

        # Determine delay reason
        delay_reason = "by_predecessor" if causing_predecessors else "by_itself"

        # Analyze impact (successors)
        impacted_successors = find_impacted_successors(
            task_code, start_delayed, end_delayed, updated_activities
        )

        delayed_activities.append({
            'task_code': task_code,
            'task_name': updated.get('task_name', ''),
            'baseline_start': baseline.get('planned_start_date'),
            'baseline_end': baseline.get('planned_end_date'),
            'updated_start': updated.get('planned_start_date'),
            'updated_end': updated.get('planned_end_date'),
            'start_delay_days': round(start_delay_days, 1) if start_delay_days else 0,
            'end_delay_days': round(end_delay_days, 1) if end_delay_days else 0,
            'delay_reason': delay_reason,
            'causing_predecessors': causing_predecessors,
            'impacted_successors': impacted_successors
        })

    return delayed_activities


def generate_json_output(
    delayed_activities: List[dict],
    total_activities: int,
    analysis_info: dict,
    report_type: str = "all",
    critical_path_impact: Optional[dict] = None
) -> dict:
    """Generate JSON output structure."""
    by_itself_count = sum(1 for a in delayed_activities if a['delay_reason'] == 'by_itself')
    by_predecessor_count = sum(1 for a in delayed_activities if a['delay_reason'] == 'by_predecessor')

    result = {
        'analysis_info': analysis_info,
        'report_type': report_type,
        'summary': {
            'total_activities_analyzed': total_activities,
            'delayed_count': len(delayed_activities),
            'by_itself_count': by_itself_count,
            'by_predecessor_count': by_predecessor_count
        }
    }

    # Add critical path impact for critical reports
    if report_type == "critical" and critical_path_impact:
        result['critical_path_impact'] = critical_path_impact

    result['delayed_activities'] = delayed_activities
    return result


def format_date_short(date_str: Optional[str]) -> str:
    """Format ISO date string to short format (YYYY-MM-DD)."""
    if not date_str:
        return 'N/A'
    dt = parse_date(date_str)
    if not dt:
        return 'N/A'
    return dt.strftime('%Y-%m-%d')


def generate_markdown_output(
    delayed_activities: List[dict],
    total_activities: int,
    analysis_info: dict,
    report_type: str = "all",
    critical_path_impact: Optional[dict] = None
) -> str:
    """Generate Markdown report."""
    by_itself = [a for a in delayed_activities if a['delay_reason'] == 'by_itself']
    by_predecessor = [a for a in delayed_activities if a['delay_reason'] == 'by_predecessor']

    if report_type == "critical":
        title = "# P6 Critical Path Delay Analysis Report"
        activities_label = "Critical Path Activities"
    else:
        title = "# P6 All Delays Analysis Report"
        activities_label = "Total Activities Analyzed"

    lines = [
        title,
        "",
        f"**Project**: {analysis_info.get('updated_project_code', 'N/A')}",
        f"**Analysis Date**: {analysis_info.get('analysis_date', 'N/A')[:10]}",
        f"**Baseline**: {analysis_info.get('baseline_file', 'N/A')} ({analysis_info.get('baseline_project_code', '')})",
        f"**Updated**: {analysis_info.get('updated_file', 'N/A')} ({analysis_info.get('updated_project_code', '')})",
        "",
    ]

    # Add critical path impact section for critical reports
    if report_type == "critical" and critical_path_impact:
        delay_days = critical_path_impact.get('project_delay_days', 0)
        terminal = critical_path_impact.get('terminal_activity', {})

        lines.extend([
            "---",
            "",
            "## ⚠️ Project Delay Impact",
            "",
            f"**Project Completion Delayed by: {delay_days} days**",
            "",
            "| Terminal Activity | Baseline End | Updated End | Delay |",
            "|-------------------|--------------|-------------|-------|",
            f"| {terminal.get('task_code', 'N/A')} - {terminal.get('task_name', 'N/A')} | {format_date_short(terminal.get('baseline_end'))} | {format_date_short(terminal.get('updated_end'))} | **+{delay_days} days** |",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| {activities_label} | {total_activities} |",
        f"| Delayed Activities | {len(delayed_activities)} |",
        f"| Delayed by Itself | {len(by_itself)} |",
        f"| Delayed by Predecessor | {len(by_predecessor)} |",
        "",
        "---",
        ""
    ])

    # Delays by Itself section
    lines.append("## Delays by Itself (Action Required)")
    lines.append("")
    lines.append("These activities are the source of delays - no predecessor can explain their slippage.")
    lines.append("")

    if not by_itself:
        lines.append("*No activities delayed by itself.*")
        lines.append("")
    else:
        for i, activity in enumerate(by_itself, 1):
            lines.append(f"### {i}. {activity['task_code']} - {activity['task_name']}")
            lines.append("")
            lines.append("| | Baseline | Updated | Delay |")
            lines.append("|--|----------|---------|-------|")

            start_delay = activity['start_delay_days']
            end_delay = activity['end_delay_days']
            start_delay_str = f"**+{start_delay} days**" if start_delay > 0 else f"{start_delay} days"
            end_delay_str = f"**+{end_delay} days**" if end_delay > 0 else f"{end_delay} days"

            lines.append(f"| Start | {format_date_short(activity['baseline_start'])} | {format_date_short(activity['updated_start'])} | {start_delay_str} |")
            lines.append(f"| End | {format_date_short(activity['baseline_end'])} | {format_date_short(activity['updated_end'])} | {end_delay_str} |")
            lines.append("")

            if activity['impacted_successors']:
                lines.append("**Impacted Successors:**")
                for succ in activity['impacted_successors']:
                    lines.append(f"- `{succ['task_code']}` - {succ['task_name']} ({succ['dependency_type']})")
            else:
                lines.append("**Impacted Successors:** None")
            lines.append("")
            lines.append("---")
            lines.append("")

    # Delays by Predecessor section
    lines.append("## Delays by Predecessor")
    lines.append("")
    lines.append("These activities are delayed due to upstream dependencies.")
    lines.append("")

    if not by_predecessor:
        lines.append("*No activities delayed by predecessor.*")
        lines.append("")
    else:
        for i, activity in enumerate(by_predecessor, 1):
            lines.append(f"### {i}. {activity['task_code']} - {activity['task_name']}")
            lines.append("")
            lines.append("| | Baseline | Updated | Delay |")
            lines.append("|--|----------|---------|-------|")

            start_delay = activity['start_delay_days']
            end_delay = activity['end_delay_days']
            start_delay_str = f"**+{start_delay} days**" if start_delay > 0 else f"{start_delay} days"
            end_delay_str = f"**+{end_delay} days**" if end_delay > 0 else f"{end_delay} days"

            lines.append(f"| Start | {format_date_short(activity['baseline_start'])} | {format_date_short(activity['updated_start'])} | {start_delay_str} |")
            lines.append(f"| End | {format_date_short(activity['baseline_end'])} | {format_date_short(activity['updated_end'])} | {end_delay_str} |")
            lines.append("")

            if activity['causing_predecessors']:
                lines.append("**Caused By:**")
                for pred in activity['causing_predecessors']:
                    lines.append(f"- `{pred['task_code']}` - {pred['task_name']} ({pred['dependency_type']})")
            lines.append("")

            if activity['impacted_successors']:
                lines.append("**Impacted Successors:**")
                for succ in activity['impacted_successors']:
                    lines.append(f"- `{succ['task_code']}` - {succ['task_name']} ({succ['dependency_type']})")
            else:
                lines.append("**Impacted Successors:** None")
            lines.append("")
            lines.append("---")
            lines.append("")

    # Appendix
    lines.append("## Appendix: All Delayed Activities")
    lines.append("")
    lines.append("| Task Code | Task Name | Delay Reason | Start Delay | End Delay |")
    lines.append("|-----------|-----------|--------------|-------------|-----------|")

    for activity in delayed_activities:
        start_delay = activity['start_delay_days']
        end_delay = activity['end_delay_days']
        start_str = f"+{start_delay} days" if start_delay > 0 else f"{start_delay} days"
        end_str = f"+{end_delay} days" if end_delay > 0 else f"{end_delay} days"

        # Truncate task name if too long
        task_name = activity['task_name']
        if len(task_name) > 50:
            task_name = task_name[:47] + "..."

        lines.append(f"| {activity['task_code']} | {task_name} | {activity['delay_reason']} | {start_str} | {end_str} |")

    lines.append("")

    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description='P6Analyzer - Schedule Delay Analysis Tool for Oracle Primavera P6',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Analyze all delays only
  python p6analyzer.py baseline.json updated.json

  # Analyze all delays + critical path delays
  python p6analyzer.py baseline.json updated.json critical_path.json

  # With output directory
  python p6analyzer.py baseline.json updated.json critical_path.json -d output/

Output files (always generated):
  - all_delays.json      All delayed activities (JSON)
  - all_delays.md        All delayed activities (Markdown)

Output files (only when critical_path provided):
  - critical_delays.json Critical path delays only (JSON)
  - critical_delays.md   Critical path delays only (Markdown)
        '''
    )

    parser.add_argument('baseline', help='Path to baseline schedule JSON file')
    parser.add_argument('updated', help='Path to updated schedule JSON file')
    parser.add_argument('critical_path', nargs='?', help='Path to critical path JSON file (optional)')
    parser.add_argument('-d', '--output-dir', default='.',
                        help='Output directory (default: current directory)')

    args = parser.parse_args()

    # Load data
    print(f"Loading baseline schedule: {args.baseline}")
    baseline_activities, baseline_project = load_activities(args.baseline)
    print(f"  Loaded {len(baseline_activities)} activities")

    print(f"Loading updated schedule: {args.updated}")
    updated_activities, updated_project = load_activities(args.updated)
    print(f"  Loaded {len(updated_activities)} activities")

    # Conditionally load critical path
    critical_tasks = set()
    if args.critical_path:
        print(f"Loading critical path: {args.critical_path}")
        critical_tasks, cp_project, cp_summary = load_critical_path(args.critical_path)
        print(f"  Found {len(critical_tasks)} activities on critical path")
    else:
        print("No critical path file provided - skipping critical path analysis")

    # Prepare analysis info
    analysis_info = {
        'analysis_date': datetime.now().isoformat(),
        'baseline_file': args.baseline.split('/')[-1],
        'updated_file': args.updated.split('/')[-1],
        'baseline_project_code': baseline_project.get('project_code', ''),
        'updated_project_code': updated_project.get('project_code', '')
    }
    if args.critical_path:
        analysis_info['critical_path_file'] = args.critical_path.split('/')[-1]

    # Analyze ALL delays (activities that exist in both baseline and updated)
    print("\nAnalyzing all delays...")
    all_task_codes = set(baseline_activities.keys()) & set(updated_activities.keys())
    all_delayed = analyze_delays(all_task_codes, baseline_activities, updated_activities)
    print(f"  Found {len(all_delayed)} delayed activities (out of {len(all_task_codes)} common activities)")

    # Conditionally analyze critical path delays
    critical_delayed = []
    critical_path_impact = None
    if args.critical_path:
        # Filter to critical path delays
        print("Filtering critical path delays...")
        critical_delayed = [a for a in all_delayed if a['task_code'] in critical_tasks]
        print(f"  Found {len(critical_delayed)} delayed activities on critical path")

        # Calculate critical path impact (project delay)
        print("Calculating critical path impact...")
        critical_path_impact = calculate_critical_path_impact(
            critical_tasks, baseline_activities, updated_activities
        )
        if critical_path_impact:
            print(f"  Project delayed by {critical_path_impact['project_delay_days']} days")

    # Ensure output directory exists
    output_dir = args.output_dir
    if output_dir and output_dir != '.':
        os.makedirs(output_dir, exist_ok=True)

    # Generate all_delays outputs
    all_json = generate_json_output(all_delayed, len(all_task_codes), analysis_info, "all")
    all_md = generate_markdown_output(all_delayed, len(all_task_codes), analysis_info, "all")

    # Write output files
    print("\nWriting output files...")

    all_json_path = os.path.join(output_dir, 'all_delays.json')
    with open(all_json_path, 'w', encoding='utf-8') as f:
        json.dump(all_json, f, indent=2, ensure_ascii=False)
    print(f"  {all_json_path}")

    all_md_path = os.path.join(output_dir, 'all_delays.md')
    with open(all_md_path, 'w', encoding='utf-8') as f:
        f.write(all_md)
    print(f"  {all_md_path}")

    # Conditionally generate and write critical_delays outputs
    if args.critical_path:
        critical_json = generate_json_output(critical_delayed, len(critical_tasks), analysis_info, "critical", critical_path_impact)
        critical_md = generate_markdown_output(critical_delayed, len(critical_tasks), analysis_info, "critical", critical_path_impact)

        critical_json_path = os.path.join(output_dir, 'critical_delays.json')
        with open(critical_json_path, 'w', encoding='utf-8') as f:
            json.dump(critical_json, f, indent=2, ensure_ascii=False)
        print(f"  {critical_json_path}")

        critical_md_path = os.path.join(output_dir, 'critical_delays.md')
        with open(critical_md_path, 'w', encoding='utf-8') as f:
            f.write(critical_md)
        print(f"  {critical_md_path}")

    # Print summary
    all_by_itself = sum(1 for a in all_delayed if a['delay_reason'] == 'by_itself')
    all_by_predecessor = sum(1 for a in all_delayed if a['delay_reason'] == 'by_predecessor')

    print("\n" + "=" * 60)
    print("ANALYSIS SUMMARY")
    print("=" * 60)

    # Show project delay impact if critical path was analyzed
    if critical_path_impact:
        delay_days = critical_path_impact['project_delay_days']
        terminal = critical_path_impact['terminal_activity']
        print(f"PROJECT COMPLETION DELAYED BY: {delay_days} days")
        print(f"Terminal Activity: {terminal['task_code']}")
        print("-" * 60)

    if args.critical_path:
        # Two-column summary when critical path is provided
        critical_by_itself = sum(1 for a in critical_delayed if a['delay_reason'] == 'by_itself')
        critical_by_predecessor = sum(1 for a in critical_delayed if a['delay_reason'] == 'by_predecessor')

        print(f"{'':30} {'All':>12} {'Critical':>12}")
        print("-" * 60)
        print(f"{'Total Activities Analyzed':30} {len(all_task_codes):>12} {len(critical_tasks):>12}")
        print(f"{'Delayed Activities':30} {len(all_delayed):>12} {len(critical_delayed):>12}")
        print(f"{'  - By Itself':30} {all_by_itself:>12} {critical_by_itself:>12}")
        print(f"{'  - By Predecessor':30} {all_by_predecessor:>12} {critical_by_predecessor:>12}")
    else:
        # Single-column summary when no critical path provided
        print(f"{'':30} {'All':>12}")
        print("-" * 60)
        print(f"{'Total Activities Analyzed':30} {len(all_task_codes):>12}")
        print(f"{'Delayed Activities':30} {len(all_delayed):>12}")
        print(f"{'  - By Itself':30} {all_by_itself:>12}")
        print(f"{'  - By Predecessor':30} {all_by_predecessor:>12}")

    print("=" * 60)


if __name__ == '__main__':
    main()
