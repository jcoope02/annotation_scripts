# Nobl9 Annotations Scripts

A collection of Python scripts for managing Nobl9 SLO annotations. This folder contains tools for creating, retrieving, and analyzing annotations via the Nobl9 Annotations API. Windows support has not been added yet.

## Scripts Overview

### 1. `annotation_creator.py` - Interactive Annotation Creation
**Purpose**: Create bulk annotations interactively with support for project, service, or individual SLO level annotation creation.

**Key Features**:
- **Multiple Target Types**: Apply annotations to all SLOs in a project, service, selected individual SLOs, or composite SLOs and their components
- **Composite SLO Support**: Create annotations for composite SLOs and all their component SLOs automatically
- **Unique UUID Per Annotation**: Each annotation gets its own unique UUID identifier
- **Markdown Support**: Rich text descriptions with links
- **Timestamp Validation**: Ensures proper RFC3339 format with automatic correction
- **Custom Instance Support**: Works with all types of Nobl9 organizations
- **Comprehensive Logging**: All actions logged to local files with timestamps
- **Interactive UI**: Color-coded terminal output with clear guidance

### 2. `get_annotations.py` - Annotation Retrieval and Analysis
**Purpose**: Fetch, sort, and export annotations from Nobl9 with filtering and reporting capabilities.

**Key Features**:
- **Time-based Filtering**: Filter annotations by custom time periods
- **Type-based Filtering**: Filter by annotation categories/types
- **Multiple Export Formats**: CSV, JSON, and Excel export options
- **Custom Instance Support**: Works with all types of Nobl9 organizations
- **Comprehensive Analysis**: Annotation type analysis and statistics
- **Flexible Output**: Display in terminal or export to files

## Quick Start

### Prerequisites

- Python 3.6+
- `sloctl` CLI tool installed and configured
- Nobl9 account with API access
- Required Python packages (see individual script sections)

### Installation

1. **Install Python dependencies**:
   ```bash
   pip3 install requests PyYAML toml pandas openpyxl tabulate
   ```

2. **Install sloctl CLI**:
   ```bash
   # Follow instructions at https://docs.nobl9.com/sloctl/
   ```

3. **Configure Nobl9 context**:
   ```bash
   sloctl config add-context
   ```

## 📖 Script Details

### annotation_creator.py

#### Usage
```bash
python3 annotation_creator.py
```

#### What It Does
1. **Startup**: Shows format guidance and UUID generation info
2. **Context Selection**: Lists available Nobl9 contexts (including custom instances)
3. **Authentication**: Automatically retrieves access tokens
4. **SLO Discovery**: Fetches all available SLOs from your Nobl9 instance
5. **Target Selection**: Choose how to apply annotations:
   - **Project**: Apply to all SLOs in a specific project
   - **Service**: Apply to all SLOs in a specific service
   - **Individual**: Select specific SLOs by number
   - **Composite**: Apply to a composite SLO and all its component SLOs
6. **Annotation Details**: Enter description, optional external hyperlink, and time range
7. **Creation**: Creates annotations via the Nobl9 API with progress feedback

#### Input Formats

**Annotation Names**
- **Auto-Generated**: UUID format (e.g., `c8e9b48c-b51c-413b-9235-01fb6d7af549`)
- **Benefits**: Ensures uniqueness across all SLOs, avoids naming conflicts
- **Format**: Standard UUID v4 (8-4-4-4-12 hexadecimal characters)

**Descriptions**
- **Format**: Free text with support for special characters and Markdown formatting
- **Markdown Support**: Links, bold text, lists, and other Markdown features
- **Examples**: 
  - `Scheduled maintenance window`
  - `Ticket #12345 - Database migration`
  - `Alert from #ops-team channel`
  - `Incident resolved\n\n[View Ticket](https://jira.company.com/TICKET-123)`

**Timestamps**
- **Format**: RFC3339 (e.g., `2025-01-27T10:00:00Z`)
- **Validation**: Automatic format checking and correction
- **Examples**: 
  - `2025-01-27T10:00:00Z`
  - `2025-01-27T10:00:00:11Z` (too many colons)

#### Markdown Features

Nobl9 annotations support Markdown formatting in descriptions. The script includes an interactive external hyperlink addition feature:

**Supported Markdown Features**
- **Links**: `[Link Text](URL)` - Added interactively via the script
- **Bold**: `**bold text**`
- **Italic**: `*italic text*`
- **Lists**: `- item 1\n- item 2`
- **Code**: `` `code` ``
- **Headers**: `# Header 1`, `## Header 2`

**External Hyperlink Addition**
The script prompts you to add external hyperlinks after entering the description:
1. Enter external hyperlink text (optional - press Enter to skip)
2. If hyperlink text is provided, enter the URL
3. The script automatically formats it as Markdown and appends to description

#### Composite SLO Support

The script includes special support for composite SLOs, which are SLOs that aggregate multiple component SLOs:

**Composite SLO Detection**
- Automatically detects composite SLOs by looking for `composite` objectives
- Extracts component SLO references from the composite definition
- Shows user-friendly display names with internal names for reference

**Composite Annotation Process**
When you select a composite SLO:
1. **Composite SLO**: Creates an annotation for the composite SLO itself
2. **Component SLOs**: Creates annotations for all component SLOs that make up the composite
3. **Visual Feedback**: Shows which components will be affected with their display names
4. **Progress Tracking**: Reports success for both composite and component annotations

**Example Composite Session**
```
Found 2 composite SLO(s):
  [1] Site A Composite (d5c85e0d-c32e-4817-9b8c-1376fdaca492, Project: network, 3 component SLOs)
  [2] User Experience (user-experience, Project: mobile-app, 2 component SLOs)

Select a composite SLO by number: 1

This will create annotations for:
  • Composite SLO: Site A Composite
  • 3 component SLOs:
    1. Network Latency (Project: network)
    2. Network Loss (Project: network)
    3. Network Throughput (Project: network)

Creating annotation for composite SLO: Site A Composite
Creating annotations for 3 component SLOs
✓ Created annotation 'uuid-1' for SLO 'Site A Composite'
✓ Created annotation 'uuid-2' for SLO 'Network Latency'
✓ Created annotation 'uuid-3' for SLO 'Network Loss'
✓ Created annotation 'uuid-4' for SLO 'Network Throughput'
```

#### Example Session
```
Nobl9 Annotation Creator
========================================

Note: Each annotation will get a unique UUID
   (ensures uniqueness across all SLOs)

Available contexts:
  [1] production
  [2] staging (Custom: https://staging.nobl9.com)

Select context [1-2]: 1
Access token acquired
Retrieved 25 SLOs

Main Menu:
Choose how to apply annotations:
  [1] Apply to all SLOs in a Project
  [2] Apply to all SLOs in a Service
  [3] Apply to selected individual SLOs
  [4] Apply to Composite SLO and all its components
  [x] Exit

Select an option: 1

Projects:
  [1] default (15 SLOs)
  [2] monitoring (10 SLOs)

Select a project by number: 1
Selected project: default

Enter annotation description: Ticket #12345 - Scheduled maintenance window
Enter external hyperlink text (optional, press Enter to skip): View JIRA Ticket
Enter URL: https://jira.company.com/TICKET-123
Added link: [View JIRA Ticket](https://jira.company.com/TICKET-123)
Enter start time (ISO format, e.g., 2025-01-27T15:30:45Z): 2025-01-27T22:00:00Z
Enter end time (ISO format, e.g., 2025-01-27T15:30:45Z): 2025-01-28T02:00:00Z

Creating annotations for 15 SLOs
Creating annotation c8e9b48c-b51c-413b-9235-01fb6d7af549 for SLO 'api-availability'
Created annotation 'c8e9b48c-b51c-413b-9235-01fb6d7af549' for SLO 'api-availability'
...
Annotation creation complete: 15/15 successful
```

### get_annotations.py

#### Usage
```bash
python3 get_annotations.py
```

#### What It Does
1. **Context Selection**: Choose Nobl9 context (auto-selects if only one available)
2. **Authentication**: Retrieves access token using credentials
3. **Time Period Selection**: Choose predefined periods or enter custom dates
4. **Annotation Retrieval**: Fetches annotations from Nobl9 API
5. **Type Analysis**: Analyzes available annotation types
6. **Type Selection**: Choose single, multiple, or all annotation types
7. **Display**: Show results in formatted table
8. **Export**: Export to CSV, JSON, or Excel (optional)
9. **Loop**: Option to select different types or exit

#### Time Period Options
- **Past 24 hours**
- **Past 7 days**
- **Past 14 days**
- **Past 30 days**
- **Specific day** (enter date in YYYY-MM-DD format)
- **Custom range** (enter start and end timestamps)

#### Export Formats
- **CSV**: Comma-separated values for spreadsheet analysis
- **JSON**: Structured data for programmatic use
- **Excel**: Multi-sheet Excel file with formatting

#### Type Selection
The script supports flexible annotation type selection:
- **Single type**: Enter a number (e.g., `1` for first type)
- **Multiple types**: Enter comma-separated numbers (e.g., `1,3,5`)
- **All types**: Enter `0` (or `0,1,5` - 0 overrides other selections)
- **Input validation**: Invalid numbers are ignored with clear error messages

#### Example Session
```
Available contexts:
  [1] production
  [2] staging

Select a context: 1
Authentication successful

Select time period:
  [1] Past 24 hours
  [2] Past 7 days
  [3] Past 14 days
  [4] Past 30 days
  [5] Specific day
  [6] Custom range

Enter choice: 2

Fetching annotations...
Time range: 2025-01-20T00:00:00Z to 2025-01-27T00:00:00Z
Progress:
  Making API request... Found 45 annotations

Annotation collection complete!
Total annotations retrieved: 45

Annotation Types Found:
  - deployment (15 annotations)
  - maintenance (12 annotations)
  - incident (8 annotations)
  - other (10 annotations)

Select annotation types to view:
  [0] All annotation types
  [1] deployment (15 annotations)
  [2] maintenance (12 annotations)
  [3] incident (8 annotations)
  [4] other (10 annotations)
  Or enter multiple numbers (comma-separated, e.g., 1,3,5)

Enter choice: 1,3

Annotation Table (23 annotations):
┌─────────────────────┬─────────────┬─────────────┬─────────────────────┬─────────────┬─────────────┐
│ Time                │ Type        │ Description │ SLOs                │ Projects    │             │
├─────────────────────┼─────────────┼─────────────┼─────────────────────┼─────────────┼─────────────┤
│ 01/25/25 14:30      │ deployment  │ Production deploy... │ api-availability │ default     │             │
│ 01/24/25 10:00      │ incident    │ Database outage...   │ api-latency      │ default     │             │
└─────────────────────┴─────────────┴─────────────┴─────────────────────┴─────────────┴─────────────┘

Export options:
  [1] CSV
  [2] JSON (full details)
  [3] Excel
  [Enter] Skip export

Select export format: 1
Exported to export_annotations/annotations_production_20250127_1430.csv

Options:
  [1] Select different annotation types
  [2] Exit

Enter choice: 2
Exiting...
```

## Configuration

### TOML Configuration
Both scripts read from `~/.config/nobl9/config.toml`:

```toml
[contexts]
[contexts.my-context]
clientId = "your-client-id"
clientSecret = "your-client-secret"
accessToken = "optional-existing-token"

# For custom instances
[contexts.custom-context]
clientId = "your-client-id"
clientSecret = "your-client-secret"
accessToken = "optional-existing-token"
url = "https://custom.nobl9.com/api"
oktaOrgURL = "https://xxxxxxx"
oktaAuthServer = "xxxxxxxxxx"
```

### Logging
- **Location**: `./annotation_logs/` (annotation_creator.py)
- **Format**: `annotation_creator_YYYYMMDD_HHMMSS.log`
- **Content**: All actions, errors, and API responses

## Dependencies

### annotation_creator.py
- `requests` - HTTP API calls
- `PyYAML` - YAML processing
- `toml` - TOML configuration parsing
- `sloctl` CLI - SLO data retrieval

### get_annotations.py
- `requests` - HTTP API calls
- `pandas` - Data manipulation and analysis
- `openpyxl` - Excel file export
- `toml` - TOML configuration parsing
- `tabulate` - Terminal table formatting
- `sloctl` CLI - Context management

## Error Handling

Both scripts handle various error scenarios:

- **Invalid timestamps**: Automatic format validation and correction
- **API errors**: Detailed error messages with response details
- **Network issues**: Graceful handling with retry guidance
- **Missing dependencies**: Clear installation instructions
- **Configuration issues**: Helpful error messages and fallback options

## Use Cases

### annotation_creator.py
- **Scheduled Maintenance**: Create annotations for planned maintenance windows
- **Incident Response**: Document incidents and their impact on SLOs
- **Deployment Tracking**: Mark deployment windows and their effects
- **Change Management**: Document changes and their expected impact

### get_annotations.py
- **Audit and Compliance**: Review annotation history for compliance reporting
- **Incident Analysis**: Analyze patterns in incident-related annotations
- **Performance Review**: Review maintenance and deployment frequency
- **Data Export**: Export annotation data for external analysis tools

## API Reference

Both scripts use the [Nobl9 Annotations API](https://docs.nobl9.com/api/annotations/):

- **Endpoint**: `/api/annotations`
- **Method**: GET (retrieval), POST (creation)
- **Authentication**: Bearer token
- **Rate Limits**: See Nobl9 documentation

## Troubleshooting

### Common Issues

1. **"sloctl not found"**
   - Install sloctl: https://docs.nobl9.com/sloctl/
   - Ensure it's in your PATH

2. **"Config not found"**
   - Run `sloctl config add-context` to create configuration
   - Check file permissions on `~/.config/nobl9/config.toml`

3. **"Missing organization"**
   - Verify organization ID in TOML config
   - Check that your credentials have proper permissions

4. **"Invalid time format"**
   - Use RFC3339 format: `YYYY-MM-DDTHH:MM:SSZ`
   - Avoid extra colons or spaces

5. **"Field validation failed"**
   - Each annotation gets a unique UUID (no manual input)
   - Check that timestamps are in correct format

### Debug Mode

For detailed debugging, check the log files in `./annotation_logs/` for:
- API request/response details
- Error messages and stack traces
- User input validation results

## Contributing

To contribute to these scripts:

1. Follow PEP 8 style guidelines
2. Add comprehensive error handling
3. Include logging for all operations
4. Test with both Nobl9 Cloud and custom instances
5. Update this README with any new features

## License

These scripts are provided as-is for use with Nobl9 services.

## Support

For issues with these scripts:
1. Check the log files for detailed error information
2. Verify your Nobl9 configuration
3. Ensure all dependencies are installed

For Nobl9 API issues, refer to the [Nobl9 documentation](https://docs.nobl9.com/).

## Additional Resources

- [Nobl9 Annotations API Documentation](https://docs.nobl9.com/api/annotations/)
- [Nobl9 Annotations UI Guide](https://docs.nobl9.com/features/slo-annotations/annotations-ui/)
- [Markdown Guide](https://docs.nobl9.com/features/slo-annotations/annotations-ui/#markdown-features)
- [sloctl Documentation](https://docs.nobl9.com/sloctl/) 