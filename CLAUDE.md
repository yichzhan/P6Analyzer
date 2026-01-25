# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**See [FUNCTIONAL_DESIGN.md](FUNCTIONAL_DESIGN.md) for detailed functional specifications.**

## Project Overview

**P6Analyzer** is a schedule delay analysis tool for Oracle Primavera P6 project data.

**Purpose**: Identify delayed activities on the critical path and analyze:
- **Cause**: Whether delay is `by_itself` (root cause) or `by_predecessor` (inherited)
- **Impact**: Which direct successor tasks will be affected

**Inputs** (3 JSON files converted from P6 XER exports):
1. **Baseline schedule** - Original planned schedule with activities, dates, dependencies
2. **Updated schedule** - Current/revised schedule (same structure)
3. **Critical path** - Activities on the critical path from updated schedule

**Output** (4 files generated):
- `all_delays.json` / `all_delays.md` - ALL delayed activities in the project
- `critical_delays.json` / `critical_delays.md` - Only delays on the critical path

## Build & Development Commands

```bash
# Basic usage (outputs to current directory)
python p6analyzer.py <baseline.json> <updated.json> <critical_path.json>

# With output directory
python p6analyzer.py <baseline.json> <updated.json> <critical_path.json> -d <output_dir>
```

**Options:**
- `-d, --output-dir` - Output directory (default: current directory)

No pip install required - uses Python standard library only.

**Test with sample files:**
```bash
python p6analyzer.py Sample_file/Schedule_Baseline_activities.json \
    Sample_file/Schedule_Updated_activities.json \
    Sample_file/Schedule_Updated_critical_path.json \
    -d Output
```

## Architecture

```
p6analyzer.py                       # Single-file CLI tool (~600 lines)
├── load_activities()               # Load JSON, index by task_code
├── load_critical_path()            # Extract critical path task_codes
├── calculate_critical_path_impact()# Project delay from terminal activity
├── analyze_delays()                # Main analysis loop
│   ├── check_predecessor_caused_delay()  # Cause analysis
│   └── find_impacted_successors()        # Impact analysis
├── generate_json_output()          # JSON report
└── generate_markdown_output()      # Markdown report
```

## Input File Formats (JSON)

### Activity Schedule (Baseline & Updated)
```json
{
  "project": { "project_code": "...", "project_name": "..." },
  "activities": [
    {
      "task_code": "0000MSPM0000010",
      "task_name": "Start of eDED Phase",
      "planned_start_date": "2022-03-01T08:00:00Z",
      "planned_end_date": "2022-03-01T08:00:00Z",
      "actual_start_date": "2022-03-01T08:00:00Z",  // null if not started
      "actual_end_date": "2022-03-01T08:00:00Z",
      "dependencies": {
        "predecessors": [{ "task_code": "...", "dependency_type": "FS", "lag_hours": 0.0 }],
        "successors": [{ "task_code": "...", "dependency_type": "FS", "lag_hours": 0.0 }]
      }
    }
  ]
}
```

### Critical Path
```json
{
  "project": { "project_code": "...", "project_name": "..." },
  "summary": { "critical_path_count": 2, "total_activities_on_critical_paths": 51 },
  "critical_paths": [
    {
      "path_id": 1,
      "is_primary": true,
      "activities": [
        { "sequence": 1, "task_code": "...", "task_name": "...", "planned_start_date": "...", "planned_end_date": "..." }
      ]
    }
  ]
}
```

## Key Design Decisions

- **Python with stdlib only** - No external dependencies for easy deployment
- **JSON input** - From P6 converter tools
- **Dual output** - Both JSON (machine-readable) and Markdown (human-readable)
- **Delay detection** - Compare both `planned_start_date` and `planned_end_date` between baseline and updated
- **Impact tracing** - Direct successors only (not full chain)
- **New activities** - Ignore activities that exist in updated but not baseline
- **Dependency-aware analysis** - FS/FF use end dates, SS/SF use start dates

## Analysis Model

### Two-Direction Analysis for Each Delayed Critical Activity:

**1. Cause Analysis (← Predecessors)**
- `delay_reason: "by_itself"` - No predecessor delay can explain this activity's delay
- `delay_reason: "by_predecessor"` - At least one predecessor's delay propagated to this activity

**2. Impact Analysis (→ Successors)**
- Identify direct successors affected by this delay
- Consider dependency type: FS/FF check end date, SS/SF check start date

## Output Format

Both `all_delays` and `critical_delays` files share the same structure. The `critical_delays` output includes an additional `critical_path_impact` section.

### JSON Structure
```json
{
  "report_type": "critical",
  "summary": {
    "total_activities_analyzed": 51,
    "delayed_count": 26,
    "by_itself_count": 1,
    "by_predecessor_count": 25
  },
  "critical_path_impact": {
    "project_delay_days": 15,
    "terminal_activity": {
      "task_code": "0000MSSU0000010",
      "task_name": "Project Complete",
      "baseline_end": "2026-02-28T16:00:00Z",
      "updated_end": "2026-03-15T16:00:00Z"
    }
  },
  "delayed_activities": [...]
}
```

The `critical_path_impact` shows the project completion delay based on the terminal activity (latest end date on critical path).
