# P6Analyzer - Functional Design Document

## 1. Overview

**P6Analyzer** is a schedule delay analysis tool for Oracle Primavera P6 project data.

**Purpose**: Identify delayed activities on the critical path and analyze:
1. **Cause** - Whether the delay originated at this activity or was inherited from predecessors
2. **Impact** - Which direct successor tasks will be affected

## 2. Input Files

Two to three JSON files converted from P6 XER exports:

| File | Required | Description |
|------|----------|-------------|
| Baseline Schedule | Yes | Original planned schedule with activities, dates, dependencies |
| Updated Schedule | Yes | Current/revised schedule (same structure as baseline) |
| Critical Path | Optional | Activities on the critical path from the updated schedule |

**Note**: When critical path is not provided, only `all_delays` outputs are generated.

### 2.1 Activity Schedule Format (Baseline & Updated)

```json
{
  "project": {
    "project_code": "BIG_CR_L3_F05_UP0331",
    "project_name": ""
  },
  "activities": [
    {
      "task_code": "0000MSPM0000010",
      "task_name": "Start of eDED Phase",
      "planned_start_date": "2022-03-01T08:00:00Z",
      "planned_end_date": "2022-03-01T08:00:00Z",
      "actual_start_date": "2022-03-01T08:00:00Z",
      "actual_end_date": "2022-03-01T08:00:00Z",
      "dependencies": {
        "predecessors": [
          {
            "task_code": "PRED_TASK_CODE",
            "dependency_type": "FS",
            "lag_hours": 0.0
          }
        ],
        "successors": [
          {
            "task_code": "SUCC_TASK_CODE",
            "dependency_type": "FS",
            "lag_hours": 0.0
          }
        ]
      }
    }
  ]
}
```

### 2.2 Critical Path Format

```json
{
  "project": {
    "project_code": "BIG_CR_L3_F05_UP0825",
    "project_name": ""
  },
  "summary": {
    "total_duration_hours": 89804.0,
    "total_duration_days": 11225.5,
    "critical_path_count": 2,
    "total_activities_on_critical_paths": 51
  },
  "critical_paths": [
    {
      "path_id": 1,
      "is_primary": true,
      "duration_hours": 82684.0,
      "duration_days": 10335.5,
      "activity_count": 50,
      "activities": [
        {
          "sequence": 1,
          "task_code": "0000MSPM0000010",
          "task_name": "Start of eDED Phase",
          "planned_start_date": "2022-03-01T08:00:00Z",
          "planned_end_date": "2022-03-01T08:00:00Z"
        }
      ]
    }
  ]
}
```

## 3. Dependency Types

P6 supports four dependency relationship types:

| Type | Name | Meaning | Relevant Date |
|------|------|---------|---------------|
| **FS** | Finish-to-Start | Successor starts after predecessor finishes | Predecessor's **END** date |
| **FF** | Finish-to-Finish | Successor finishes after predecessor finishes | Predecessor's **END** date |
| **SS** | Start-to-Start | Successor starts after predecessor starts | Predecessor's **START** date |
| **SF** | Start-to-Finish | Successor finishes after predecessor starts | Predecessor's **START** date |

## 4. Analysis Algorithm

### 4.1 Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: LOAD DATA                                              │
│  - Load baseline schedule → index by task_code                  │
│  - Load updated schedule → index by task_code                   │
│  - Load critical path → extract all task_codes                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: ANALYZE ALL DELAYS                                     │
│  For each task_code in both baseline AND updated:               │
│    - Compare baseline vs updated planned_start_date             │
│    - Compare baseline vs updated planned_end_date               │
│    - If either date moved later → activity is DELAYED           │
│    - Analyze cause and impact for delayed activities            │
│    - Extract contextual notes (filter out flags/dates/status)   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: FILTER CRITICAL PATH DELAYS                            │
│  - Filter all_delays to only activities on critical path        │
│  - Create critical_delays subset                                │
│  - Calculate project delay (terminal activity end date slip)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  STEP 4: GENERATE OUTPUT                                        │
│  - all_delays.json, all_delays.md (all delayed activities)      │
│  - critical_delays.json, critical_delays.md (critical path only)│
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 Delay Detection Logic

An activity is considered **delayed** if:
- `updated.planned_start_date > baseline.planned_start_date`, OR
- `updated.planned_end_date > baseline.planned_end_date`

### 4.3 Cause Analysis Logic (delay_reason)

For a delayed activity, examine its predecessors:

```
For each predecessor in activity.dependencies.predecessors:
    Get predecessor from baseline and updated schedules

    Based on dependency_type:
        If FS or FF → check if predecessor's END date is delayed
        If SS or SF → check if predecessor's START date is delayed

    If predecessor's relevant date is delayed:
        Mark this predecessor as a potential cause

If ANY predecessor could cause the delay:
    delay_reason = "by_predecessor"
    causing_predecessors = [list of causing predecessors]
Else:
    delay_reason = "by_itself"
    causing_predecessors = []
```

### 4.4 Impact Analysis Logic (impacted_successors)

For a delayed activity, examine its successors:

```
For each successor in activity.dependencies.successors:
    Based on dependency_type:
        If FS or FF → successor is impacted if this activity's END is delayed
        If SS or SF → successor is impacted if this activity's START is delayed

    If condition met:
        Add successor to impacted_successors list
```

**Note**: Only direct successors are analyzed (not the full chain).

### 4.5 Notes Filtering (contextual notes)

Activity notes from P6 often contain a mix of flags, status indicators, date references, and meaningful contextual information. Only contextual notes are included in the output.

**Excluded patterns:**
- Single character flags (e.g., `"Y"`)
- Date patterns starting with `"A:"`, `"F:"`, or digits (e.g., `"A: 28-Sep-22(S)"`, `"19-Nov-22..."`)
- Status words: `"Not Start"`, `"cancelled"`, `"Cancelled"`, `"On-going"`, `"name changed"`, `"Free Agreement"`, `"by Site Subcontractor"`

**Included (contextual notes):**
- Explanatory text (e.g., `"acceleration schedule pending on EOTR-001 results"`)
- Condition descriptions (e.g., `"early review by 21st August, 2023"`)
- Any note that doesn't match the excluded patterns

## 5. Output Formats

### 5.1 JSON Output Structure

```json
{
  "analysis_info": {
    "analysis_date": "2026-01-22T10:30:00Z",
    "baseline_file": "Schedule_Baseline_activities.json",
    "updated_file": "Schedule_Updated_activities.json",
    "critical_path_file": "Schedule_Updated_critical_path.json",
    "baseline_project_code": "BIG_CR_L3_F05_UP0331",
    "updated_project_code": "BIG_CR_L3_F05_UP0825"
  },
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
  "delayed_activities": [
    {
      "task_code": "V021DE023100050",
      "task_name": "P&ID - IFD5",
      "baseline_start": "2023-05-20T08:00:00Z",
      "baseline_end": "2023-07-20T17:00:00Z",
      "updated_start": "2023-05-29T08:00:00Z",
      "updated_end": "2023-07-26T17:00:00Z",
      "start_delay_days": 9,
      "end_delay_days": 6,
      "delay_reason": "by_itself",
      "causing_predecessors": [],
      "impacted_successors": [
        {
          "task_code": "0000DE000000050",
          "task_name": "3D Model Update and Preparation for 90% Model Review",
          "dependency_type": "FS"
        }
      ],
      "notes": ["early review by 21st August, 2023"]
    },
    {
      "task_code": "0000DE000000050",
      "task_name": "3D Model Update and Preparation for 90% Model Review",
      "baseline_start": "2023-04-15T08:00:00Z",
      "baseline_end": "2023-07-20T17:00:00Z",
      "updated_start": "2023-05-01T08:00:00Z",
      "updated_end": "2023-08-04T17:00:00Z",
      "start_delay_days": 16,
      "end_delay_days": 15,
      "delay_reason": "by_predecessor",
      "causing_predecessors": [
        {
          "task_code": "V021DE023100050",
          "task_name": "P&ID - IFD5",
          "dependency_type": "FS"
        }
      ],
      "impacted_successors": [
        {
          "task_code": "0000DE000000060",
          "task_name": "90% 3D Model Review",
          "dependency_type": "FS"
        }
      ]
    }
  ]
}
```

### 5.2 Markdown Output Structure

For `critical_delays.md`, a Project Delay Impact section is added at the top:

```markdown
# P6 Critical Path Delay Analysis Report

**Project**: BIG_CR_L3_F05_UP0825
**Analysis Date**: 2026-01-22
**Baseline**: Schedule_Baseline_activities.json (BIG_CR_L3_F05_UP0331)
**Updated**: Schedule_Updated_activities.json (BIG_CR_L3_F05_UP0825)

---

## ⚠️ Project Delay Impact

**Project Completion Delayed by: 15 days**

| Terminal Activity | Baseline End | Updated End | Delay |
|-------------------|--------------|-------------|-------|
| 0000MSSU0000010 - Project Complete | 2026-02-28 | 2026-03-15 | **+15 days** |

---

## Summary

| Metric | Count |
|--------|-------|
| Critical Path Activities | 51 |
| Delayed Activities | 8 |
| Delayed by Itself | 2 |
| Delayed by Predecessor | 6 |

---

## Delays by Itself (Action Required)

These activities are the source of delays - no predecessor can explain their slippage.

### 1. V021DE023100050 - P&ID - IFD5

| | Baseline | Updated | Delay |
|--|----------|---------|-------|
| Start | 2023-05-20 | 2023-05-29 | **+9 days** |
| End | 2023-07-20 | 2023-07-26 | **+6 days** |

**Impacted Successors:**
- `0000DE000000050` - 3D Model Update and Preparation... (FS)

---

## Delays by Predecessor

These activities are delayed due to upstream dependencies.

### 1. 0000DE000000050 - 3D Model Update and Preparation for 90% Model Review

| | Baseline | Updated | Delay |
|--|----------|---------|-------|
| Start | 2023-04-15 | 2023-05-01 | **+16 days** |
| End | 2023-07-20 | 2023-08-04 | **+15 days** |

**Caused By:**
- `V021DE023100050` - P&ID - IFD5 (FS)

**Impacted Successors:**
- `0000DE000000060` - 90% 3D Model Review (FS)

---

## Appendix: All Delayed Activities

| Task Code | Task Name | Delay Reason | Start Delay | End Delay |
|-----------|-----------|--------------|-------------|-----------|
| V021DE023100050 | P&ID - IFD5 | by_itself | +9 days | +6 days |
| 0000DE000000050 | 3D Model Update... | by_predecessor | +16 days | +15 days |
```

## 6. Command Line Interface

```bash
# Analyze all delays only
python p6analyzer.py <baseline.json> <updated.json> [-d <output_dir>]

# Analyze all delays + critical path delays
python p6analyzer.py <baseline.json> <updated.json> <critical_path.json> [-d <output_dir>]
```

**Arguments:**
- `baseline.json` - Path to baseline schedule JSON file (required)
- `updated.json` - Path to updated schedule JSON file (required)
- `critical_path.json` - Path to critical path JSON file (optional)
- `-d <output_dir>` - Output directory (optional, defaults to current directory)

**Examples:**
```bash
# Analyze all delays only (generates 2 files)
python p6analyzer.py \
    Sample_file/Schedule_Baseline_activities.json \
    Sample_file/Schedule_Updated_activities.json \
    -d Output

# Analyze all delays + critical path delays (generates 4 files)
python p6analyzer.py \
    Sample_file/Schedule_Baseline_activities.json \
    Sample_file/Schedule_Updated_activities.json \
    Sample_file/Schedule_Updated_critical_path.json \
    -d Output
```

**Output files generated:**

Always generated:
- `all_delays.json` - All delayed activities (JSON)
- `all_delays.md` - All delayed activities (Markdown)

Only when critical_path provided:
- `critical_delays.json` - Critical path delays only (JSON)
- `critical_delays.md` - Critical path delays only (Markdown)

## 7. Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Widely available, good for data processing |
| Dependencies | stdlib only | No pip install required, easy deployment |
| Input format | JSON | Structured, easy to parse with built-in `json` module |
| Output format | JSON + Markdown | Machine-readable + human-readable |
| Delay detection | Both start and end dates | Different dependency types affect different dates |
| Impact scope | Direct successors only | Keep analysis focused; can extend later |
| New activities | Ignore | Activities in updated but not baseline are skipped |

## 8. Future Enhancements (Out of Scope)

- Full chain impact tracing (successor's successors)
- Float/slack analysis
- Resource impact analysis
- Multiple baseline comparison
- Graphical timeline visualization
