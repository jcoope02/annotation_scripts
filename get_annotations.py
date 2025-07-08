#!/usr/bin/env python3
"""
Script name: get_annotations.py

Purpose: Fetches and analyzes annotations from Nobl9 API. Retrieves annotation data including
timestamps, types, descriptions, and associated SLOs. Supports filtering by time periods,
annotation types, and offers export options in CSV, JSON, and Excel formats.

Dependencies: requests, pandas, openpyxl, toml, tabulate, sloctl CLI
Compatible with: macOS and Linux

Author: Jeremy Cooper
Date Created: 2025-07-02
"""

import requests
import sys
import json
import base64
import os
import toml
import shutil
import subprocess
import re
from datetime import datetime, timedelta

# Ensure required Python modules and sloctl CLI are available
def check_dependencies():
    missing = []
    try:
        import requests
    except ImportError:
        missing.append("requests")
    try:
        import pandas
    except ImportError:
        missing.append("pandas")
    try:
        import openpyxl
    except ImportError:
        missing.append("openpyxl")
    try:
        import toml
    except ImportError:
        missing.append("toml")
    try:
        import tabulate
    except ImportError:
        missing.append("tabulate")

    if not shutil.which("sloctl"):
        print("ERROR: 'sloctl' is not installed or not in PATH.")
        print("You can install it from https://docs.nobl9.com/sloctl/")
        sys.exit(1)

    if missing:
        print("\nMissing required Python packages:")
        for pkg in missing:
            note = " (required for Excel export)" if pkg == "openpyxl" else ""
            note = " (required for table display)" if pkg == "tabulate" else note
            print(f"  - {pkg}{note}")
        print("\nYou can install them using:")
        print("  pip3 install " + " ".join(missing))
        sys.exit(1)

# Decode JWT token to extract organization info
def decode_jwt_payload(token):
    try:
        # JWT has three parts: header.payload.signature
        payload_b64 = token.split('.')[1]
        # Add padding if necessary
        payload_b64 += '=' * (-len(payload_b64) % 4)
        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        # Look for organization in m2mProfile
        return payload.get('m2mProfile', {}).get('organization', None)
    except Exception as e:
        return None

def load_contexts_from_toml():
    default_toml_path = os.path.expanduser("~/.config/nobl9/config.toml")
    if not os.path.isfile(default_toml_path):
        print("TOML config file not found at expected path:")
        print(f"  {default_toml_path}")
        try:
            user_path = input("\nPlease provide the full path to your Nobl9 config.toml file: ").strip()
            if not os.path.isfile(user_path):
                print(f"ERROR: Could not find TOML file at {user_path}")
                return {}
            toml_path = user_path
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)
    else:
        toml_path = default_toml_path
    try:
        toml_data = toml.load(toml_path)
        raw_contexts = toml_data.get("contexts", {})
        parsed_contexts = {}
        
        for ctx_name, creds in raw_contexts.items():
            if "clientId" in creds and "clientSecret" in creds:
                # Check if this is a custom instance (has url field)
                is_custom_instance = "url" in creds
                base_url = creds.get("url")
                okta_org_url = creds.get("oktaOrgURL")
                okta_auth_server = creds.get("oktaAuthServer")
                
                parsed_contexts[ctx_name] = {
                    "clientId": creds["clientId"],
                    "clientSecret": creds["clientSecret"],
                    "accessToken": creds.get("accessToken", ""),
                    "organization": creds.get("organization", None),
                    "is_custom_instance": is_custom_instance,
                    "base_url": base_url,
                    "oktaOrgURL": okta_org_url,
                    "oktaAuthServer": okta_auth_server
                }
        return parsed_contexts
    except Exception as e:
        print(f"Failed to parse TOML config: {e}")
        return {}

def enhanced_choose_context():
    contexts_dict = load_contexts_from_toml()
    if not contexts_dict:
        print("No valid contexts found. Please ensure your config.toml is set up correctly.")
        sys.exit(1)
    context_names = list(contexts_dict.keys())
    if len(context_names) == 1:
        selected = context_names[0]
        return selected, contexts_dict[selected]
    print("\nAvailable contexts:")
    for i, name in enumerate(context_names, 1):
        print(f"  [{i}] {name}")
    try:
        choice = input("Select a context: ").strip()
        index = int(choice) - 1
        selected = context_names[index]
        return selected, contexts_dict[selected]
    except (ValueError, IndexError):
        print("ERROR: Invalid context selection.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)

def validate_date_format(date_str):
    """Validate date format YYYY-MM-DD"""
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return False
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False

def validate_timestamp_format(timestamp_str):
    """Validate RFC3339 timestamp format"""
    try:
        # Handle both with and without 'Z' suffix
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1]
        datetime.fromisoformat(timestamp_str)
        return True
    except ValueError:
        return False

def authenticate(credentials):
    client_id = credentials.get("clientId")
    client_secret = credentials.get("clientSecret")
    if not client_id or not client_secret:
        print("ERROR: Missing credentials in context.")
        sys.exit(1)
    org_id = credentials.get("organization")
    # Try decoding accessToken if organization is not in config
    if not org_id and credentials.get("accessToken"):
        org_id = decode_jwt_payload(credentials["accessToken"])
    # Check for SLOCTL_ORGANIZATION environment variable
    if not org_id:
        org_id = os.getenv("SLOCTL_ORGANIZATION")
    # Fall back to user input if no organization ID is found
    if not org_id:
        try:
            org_id = input("Enter Nobl9 Organization ID (find in Nobl9 UI under Settings > Account): ").strip()
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)
    # Validate org_id
    if not org_id:
        print("ERROR: Organization ID is required.")
        sys.exit(1)
    encoded_creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded_creds}",
        "Content-Type": "application/json",
        "Organization": org_id
    }
    
    # Check if this is a custom instance with custom base URL
    is_custom_instance = credentials.get("is_custom_instance", False)
    base_url = credentials.get("base_url")
    okta_org_url = credentials.get("oktaOrgURL")
    okta_auth_server = credentials.get("oktaAuthServer")
    
    if is_custom_instance and base_url:
        print(f"API base url: {base_url}")
        # Use custom base URL for authentication
        auth_url = f"{base_url}/accessToken"
    else:
        auth_url = "https://app.nobl9.com/api/accessToken"
    
    try:
        response = requests.post(auth_url, headers=headers, timeout=30)
        if response.status_code != 200:
            print("ERROR: Authentication failed")
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_info = error_data["error"]
                    # Check if error is a string (contains nested JSON) or a dict
                    if isinstance(error_info, str):
                        try:
                            # Look for JSON object in the error string
                            json_match = re.search(r'\{.*\}', error_info)
                            if json_match:
                                nested_error = json.loads(json_match.group())
                                print(f"  Error Code: {nested_error.get('errorCode', 'Unknown')}")
                                print(f"  Summary: {nested_error.get('errorSummary', 'No summary provided')}")
                                print(f"  Error ID: {nested_error.get('errorId', 'No ID provided')}")
                                if nested_error.get('errorCauses'):
                                    print(f"  Causes: {nested_error['errorCauses']}")
                            else:
                                # If no JSON found, show the raw error string
                                print(f"  Error: {error_info}")
                        except json.JSONDecodeError:
                            # If nested parsing fails, show the raw error string
                            print(f"  Error: {error_info}")
                    else:
                        # Error is already a dictionary
                        print(f"  Error Code: {error_info.get('errorCode', 'Unknown')}")
                        print(f"  Summary: {error_info.get('errorSummary', 'No summary provided')}")
                        print(f"  Error ID: {error_info.get('errorId', 'No ID provided')}")
                        if error_info.get('errorCauses'):
                            print(f"  Causes: {error_info['errorCauses']}")
                elif "message" in error_data:
                    print(f"  Message: {error_data['message']}")
                else:
                    print(f"  Response: {response.text}")
            except json.JSONDecodeError:
                print(f"  Raw response: {response.text}")
            sys.exit(1)
        
        token_data = response.json()
        token = token_data.get("access_token")
        if not token:
            print("ERROR: No access token in response")
            print(f"  Response: {response.text}")
            sys.exit(1)
        return token, org_id
    except requests.exceptions.Timeout:
        print("ERROR: Authentication request timed out")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Network error during authentication: {e}")
        sys.exit(1)
    except json.JSONDecodeError:
        print("ERROR: Invalid JSON response from authentication endpoint")
        print(f"  Response: {response.text}")
        sys.exit(1)

def fetch_annotations(token, org, start_time, end_time, is_custom_instance=False, custom_base_url=None):
    """Fetch annotations from the Nobl9 API with time filtering."""
    annotations = []
    
    # Use custom base URL for custom instances
    if is_custom_instance and custom_base_url:
        api_base_url = f"{custom_base_url}/annotations"
    else:
        api_base_url = "https://app.nobl9.com/api/annotations"
    
    # Add time range validation
    try:
        start_dt = datetime.fromisoformat(start_time.replace('Z', ''))
        end_dt = datetime.fromisoformat(end_time.replace('Z', ''))
        if start_dt > end_dt:
            print("ERROR: Start time is after end time")
            sys.exit(1)
    except ValueError as e:
        print(f"ERROR: Invalid timestamp format: {e}")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Organization": org,
        "Accept": "application/json; version=v1alpha",
        "Project": "*"
    }
    
    print(f"\nFetching annotations...")
    print(f"Time range: {start_time} to {end_time}")
    print("Progress:")
    
    params = {
        "from": start_time,
        "to": end_time
    }
    
    try:
        print(f"  Making API request...", end="", flush=True)
        response = requests.get(
            api_base_url,
            headers=headers,
            params=params,
            timeout=30
        )
        
        if response.status_code != 200:
            print(f"ERROR: API request failed (Status: {response.status_code})")
            try:
                error_data = response.json()
                if "error" in error_data:
                    error_info = error_data["error"]
                    # Check if error is a string (contains nested JSON) or a dict
                    if isinstance(error_info, str):
                        try:
                            # Look for JSON object in the error string
                            json_match = re.search(r'\{.*\}', error_info)
                            if json_match:
                                nested_error = json.loads(json_match.group())
                                print(f"  Error Code: {nested_error.get('errorCode', 'Unknown')}")
                                print(f"  Summary: {nested_error.get('errorSummary', 'No summary provided')}")
                                print(f"  Error ID: {nested_error.get('errorId', 'No ID provided')}")
                            else:
                                # If no JSON found, show the raw error string
                                print(f"  Error: {error_info}")
                        except json.JSONDecodeError:
                            # If nested parsing fails, show the raw error string
                            print(f"  Error: {error_info}")
                    else:
                        # Error is already a dictionary
                        print(f"  Error Code: {error_info.get('errorCode', 'Unknown')}")
                        print(f"  Summary: {error_info.get('errorSummary', 'No summary provided')}")
                        print(f"  Error ID: {error_info.get('errorId', 'No ID provided')}")
                elif "message" in error_data:
                    print(f"  Message: {error_data['message']}")
                else:
                    print(f"  Response: {response.text}")
            except json.JSONDecodeError:
                print(f"  Raw response: {response.text}")
            sys.exit(1)
        
        data = response.json()
        
        # Handle different response formats
        if isinstance(data, list):
            # API returned a list directly
            annotations = data
        elif isinstance(data, dict):
            # API returned an object with annotations key
            annotations = data.get("annotations", [])
        else:
            print(f"ERROR: Unexpected response format: {type(data)}")
            sys.exit(1)
        
        print(f" Found {len(annotations)} annotations")
        
    except requests.exceptions.Timeout:
        print("ERROR: API request timed out")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Network error during API request: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to fetch annotations: {e}")
        sys.exit(1)
    
    print(f"Annotation collection complete!")
    print(f"Total annotations retrieved: {len(annotations)}")
    
    # Sort annotations by timestamp
    annotations.sort(key=lambda x: x.get("startTime", ""), reverse=True)
    
    return annotations

def select_time_period():
    """Allow user to select time period for annotation filtering."""
    while True:
        print("\nSelect time period:")
        print("  [1] Past 24 hours")
        print("  [2] Past 7 days")
        print("  [3] Past 14 days")
        print("  [4] Past 30 days")
        print("  [5] Specific day")
        print("  [6] Custom range")
        
        try:
            choice = input("Enter choice: ").strip()
            if not choice:
                print("ERROR: Please enter a choice.")
                continue
                
            choice = int(choice)
            now = datetime.utcnow()
            
            if choice == 1:
                start_time = (now - timedelta(hours=24)).isoformat() + "Z"
                end_time = now.isoformat() + "Z"
                return start_time, end_time
            elif choice == 2:
                start_time = (now - timedelta(days=7)).isoformat() + "Z"
                end_time = now.isoformat() + "Z"
                return start_time, end_time
            elif choice == 3:
                start_time = (now - timedelta(days=14)).isoformat() + "Z"
                end_time = now.isoformat() + "Z"
                return start_time, end_time
            elif choice == 4:
                start_time = (now - timedelta(days=30)).isoformat() + "Z"
                end_time = now.isoformat() + "Z"
                return start_time, end_time
            elif choice == 5:
                while True:
                    day = input("Enter date (YYYY-MM-DD): ").strip()
                    if validate_date_format(day):
                        start_time = f"{day}T00:00:00Z"
                        end_time = f"{day}T23:59:59Z"
                        return start_time, end_time
                    else:
                        print("ERROR: Invalid date format. Please use YYYY-MM-DD")
            elif choice == 6:
                while True:
                    start_time = input("Enter start time (YYYY-MM-DDThh:mm:ssZ): ").strip()
                    if validate_timestamp_format(start_time):
                        break
                    else:
                        print("ERROR: Invalid start time format. Please use YYYY-MM-DDThh:mm:ssZ")
                
                while True:
                    end_time = input("Enter end time (YYYY-MM-DDThh:mm:ssZ): ").strip()
                    if validate_timestamp_format(end_time):
                        break
                    else:
                        print("ERROR: Invalid end time format. Please use YYYY-MM-DDThh:mm:ssZ")
                
                return start_time, end_time
            else:
                print("ERROR: Invalid choice. Please enter a number between 1 and 6.")
                continue
        except ValueError:
            print("ERROR: Invalid input. Please enter a number.")
            continue
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)

def analyze_annotation_types(annotations):
    """Analyze and display annotation types found."""
    type_counts = {}
    for annotation in annotations:
        annotation_type = annotation.get("category", "Unknown")
        type_counts[annotation_type] = type_counts.get(annotation_type, 0) + 1
    
    print("\nAnnotation Types Found:")
    for annotation_type, count in sorted(type_counts.items()):
        print(f"  - {annotation_type}: {count} annotations")
    
    return type_counts

def select_annotation_types(available_types):
    """Allow user to select specific annotation types to view."""
    type_list = list(available_types.keys())
    
    while True:
        print("\nSelect annotation types to view:")
        print("  [0] All annotation types")
        for i, annotation_type in enumerate(type_list, 1):
            count = available_types[annotation_type]
            print(f"  [{i}] {annotation_type} ({count} annotations)")
        print("  Or enter multiple numbers (comma-separated, e.g., 1,3,5)")
        
        try:
            choice = input("Enter choice: ").strip()
            
            # Handle "0" for all types
            if choice == "0":
                return set(type_list)  # Return all types
            
            # Handle comma-separated numbers
            if "," in choice:
                selected_numbers = [num.strip() for num in choice.split(",") if num.strip()]
                selected_types = set()
                has_zero = False
                
                for num_str in selected_numbers:
                    try:
                        num = int(num_str)
                        if num == 0:
                            has_zero = True
                        elif 1 <= num <= len(type_list):
                            selected_types.add(type_list[num-1])
                        else:
                            print(f"ERROR: Invalid number {num}. Must be between 0 and {len(type_list)}")
                            continue
                    except ValueError:
                        print(f"ERROR: Invalid input '{num_str}'. Must be a number.")
                        continue
                
                # If 0 is included, return all types (ignore other numbers)
                if has_zero:
                    print("Note: '0' (all types) selected - ignoring other numbers")
                    return set(type_list)
                
                if selected_types:
                    return selected_types
                else:
                    print("ERROR: No valid types selected.")
                    continue
            
            # Handle single number
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(type_list):
                    return {type_list[choice_num-1]}  # Return selected type
                else:
                    print(f"ERROR: Invalid choice. Please enter a number between 0 and {len(type_list)}, or comma-separated numbers.")
                    continue
            except ValueError:
                print("ERROR: Invalid input. Please enter a number or comma-separated numbers.")
                continue
        except KeyboardInterrupt:
            print("\nExiting...")
            sys.exit(0)

def format_timestamp(iso_string):
    """Format ISO timestamp for display."""
    try:
        dt = datetime.strptime(iso_string, "%Y-%m-%dT%H:%M:%SZ")
        return dt.strftime("%m/%d/%y %H:%M")
    except Exception:
        return iso_string

def extract_slo_and_project_names(annotation):
    """Extract SLO and project names from annotation (top-level fields)."""
    slo = annotation.get("slo")
    project = annotation.get("project")
    slo_names = [slo] if slo else []
    project_names = [project] if project else []
    return ", ".join(slo_names) if slo_names else "None", ", ".join(project_names) if project_names else "None"

def display_annotations(annotations, selected_types):
    """Display annotations in a formatted table."""
    from tabulate import tabulate
    
    # Filter annotations by selected types
    filtered_annotations = [
        ann for ann in annotations 
        if ann.get("category", "Unknown") in selected_types
    ]
    
    if not filtered_annotations:
        print(f"\nNo annotations found for selected types: {', '.join(selected_types)}")
        return
    
    # Format annotations for display
    rows = []
    for annotation in filtered_annotations:
        slos_display, projects_display = extract_slo_and_project_names(annotation)
        rows.append({
            "Time": format_timestamp(annotation.get("startTime", "")),
            "Type": annotation.get("category", ""),
            "Description": annotation.get("description", "")[:50] + "..." if len(annotation.get("description", "")) > 50 else annotation.get("description", ""),
            "SLOs": slos_display if slos_display else "None",
            "Projects": projects_display if projects_display else "None"
        })

    print(f"\nAnnotation Table ({len(filtered_annotations)} annotations):")
    print(tabulate(rows, headers="keys", tablefmt="simple"))
    
    return filtered_annotations

def export_annotations(annotations, context, export_format):
    """Export annotations to various formats."""
    import pandas as pd
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    base = f"export_annotations/annotations_{context}_{timestamp}"
    
    # Create export directory
    try:
        os.makedirs("export_annotations", exist_ok=True)
    except PermissionError:
        print("ERROR: Permission denied creating export directory")
        return
    except Exception as e:
        print(f"ERROR: Failed to create export directory: {e}")
        return
    
    if export_format == "1":  # CSV
        # Create simplified table for CSV
        rows = []
        for annotation in annotations:
            slos_str, projects_str = extract_slo_and_project_names(annotation)
            rows.append({
                "StartTime": annotation.get("startTime", ""),
                "EndTime": annotation.get("endTime", ""),
                "Type": annotation.get("category", ""),
                "Name": annotation.get("name", ""),
                "Description": annotation.get("description", ""),
                "SLOs": slos_str,
                "Projects": projects_str
            })
        
        try:
            df = pd.DataFrame(rows)
            df.to_csv(f"{base}.csv", index=False)
            print(f"Exported to {base}.csv")
        except Exception as e:
            print(f"ERROR: Failed to export CSV: {e}")
        
    elif export_format == "2":  # JSON (full details)
        try:
            with open(f"{base}.json", "w") as f:
                json.dump(annotations, f, indent=2)
            print(f"Exported to {base}.json")
        except Exception as e:
            print(f"ERROR: Failed to export JSON: {e}")
        
    elif export_format == "3":  # Excel
        # Create simplified table for Excel
        rows = []
        for annotation in annotations:
            slos_str, projects_str = extract_slo_and_project_names(annotation)
            rows.append({
                "StartTime": annotation.get("startTime", ""),
                "EndTime": annotation.get("endTime", ""),
                "Type": annotation.get("category", ""),
                "Name": annotation.get("name", ""),
                "Description": annotation.get("description", ""),
                "SLOs": slos_str,
                "Projects": projects_str
            })
        
        try:
            df = pd.DataFrame(rows)
            df.to_excel(f"{base}.xlsx", index=False)
            print(f"Exported to {base}.xlsx")
        except Exception as e:
            print(f"ERROR: Failed to export Excel: {e}")

def main():
    print("Nobl9 Annotations Tool")
    print("=" * 40)
    
    try:
        check_dependencies()
        context_name, credentials = enhanced_choose_context()
        
        token, org = authenticate(credentials)
        if not token or not org:
            print("ERROR: Authentication failed")
            sys.exit(1)
        
        # Get custom instance information from credentials
        is_custom_instance = credentials.get("is_custom_instance", False)
        custom_base_url = credentials.get("base_url")
        
        # Select time period
        start_time, end_time = select_time_period()
        
        # Fetch annotations
        annotations = fetch_annotations(token, org, start_time, end_time, is_custom_instance, custom_base_url)
        
        if not annotations:
            print("No annotations found in the specified time range.")
            sys.exit(0)
        
        # Analyze annotation types
        type_counts = analyze_annotation_types(annotations)
        
        # Main loop for annotation type selection and export
        while True:
            # Select annotation types to view
            selected_types = select_annotation_types(type_counts)
            
            # Display filtered annotations
            filtered_annotations = display_annotations(annotations, selected_types)
            
            if not filtered_annotations:
                print("No annotations found for selected types.")
                continue
            
            # Export options
            print("\nExport options:")
            print("  [1] CSV")
            print("  [2] JSON (full details)")
            print("  [3] Excel")
            print("  [Enter] Skip export")
            
            try:
                choice = input("\nSelect export format: ").strip()
                if choice in ["1", "2", "3"]:
                    export_annotations(filtered_annotations, context_name, choice)
            except KeyboardInterrupt:
                print("\nExiting...")
                sys.exit(0)
            
            # Ask if user wants to continue or exit
            print("\nOptions:")
            print("  [1] Select different annotation types")
            print("  [2] Exit")
            
            try:
                continue_choice = input("Enter choice: ").strip()
                if continue_choice == "2":
                    print("Exiting...")
                    break
                elif continue_choice != "1":
                    print("Invalid choice. Continuing with type selection...")
            except KeyboardInterrupt:
                print("\nExiting...")
                sys.exit(0)
            
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
    except Exception as e:
        print(f"ERROR: Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
    