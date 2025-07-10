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

import base64
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta

import requests
import toml
from colorama import Fore, Style, init

init(autoreset=True)


def check_dependencies():
    """Check if required dependencies are available."""
    if not shutil.which("sloctl"):
        print(f"{Fore.RED}ERROR: 'sloctl' is not installed or not in PATH.{Style.RESET_ALL}")
        print(f"{Fore.YELLOW}You can install it from https://docs.nobl9.com/sloctl/{Style.RESET_ALL}")
        sys.exit(1)

# Decode JWT token to extract organization info
def decode_jwt_payload(token):
    """Decode JWT token to extract organization info."""
    try:
        # JWT has three parts: header.payload.signature
        payload_b64 = token.split('.')[1]
        # Add padding if necessary
        payload_b64 += '=' * (-len(payload_b64) % 4)
        payload_json = base64.b64decode(payload_b64).decode('utf-8')
        payload = json.loads(payload_json)
        # Look for organization in m2mProfile
        return payload.get('m2mProfile', {}).get('organization', None)
    except Exception:
        return None

def load_contexts_from_toml():
    """Load and parse TOML configuration."""
    default_toml_path = os.path.expanduser("~/.config/nobl9/config.toml")
    if not os.path.isfile(default_toml_path):
        print(f"{Fore.YELLOW}TOML config file not found at expected path:{Style.RESET_ALL}")
        print(f"  {default_toml_path}")
        try:
            user_path = input(f"{Fore.CYAN}Please provide the full path to your Nobl9 {Style.RESET_ALL}"
                            f"{Fore.CYAN}config.toml file:{Style.RESET_ALL} ").strip()
            if not os.path.isfile(user_path):
                print(f"{Fore.RED}ERROR: Could not find TOML file at {user_path}{Style.RESET_ALL}")
                return {}
            toml_path = user_path
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
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
        print(f"{Fore.RED}Failed to parse TOML config: {e}{Style.RESET_ALL}")
        return {}

def enhanced_choose_context():
    """Enhanced context selection with custom instance support."""
    contexts_dict = load_contexts_from_toml()
    if not contexts_dict:
        print(f"{Fore.RED}No valid contexts found. Please ensure your config.toml is set up correctly.{Style.RESET_ALL}")
        sys.exit(1)
    context_names = list(contexts_dict.keys())
    if len(context_names) == 1:
        selected = context_names[0]
        return selected, contexts_dict[selected]
    print(f"\n{Fore.CYAN}Available contexts:{Style.RESET_ALL}")
    for i, name in enumerate(context_names, 1):
        print(f"  [{i}] {name}")
    try:
        choice = input(f"{Fore.CYAN}Select a context:{Style.RESET_ALL} ").strip()
        index = int(choice) - 1
        selected = context_names[index]
        return selected, contexts_dict[selected]
    except (ValueError, IndexError):
        print(f"{Fore.RED}ERROR: Invalid context selection.{Style.RESET_ALL}")
        sys.exit(1)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
        sys.exit(0)

def validate_date_format(date_str):
    """Validate date format YYYY-MM-DD."""
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return False
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except ValueError:
        return False


def validate_timestamp_format(timestamp_str):
    """Validate RFC3339 timestamp format."""
    try:
        # Handle both with and without 'Z' suffix
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1]
        datetime.fromisoformat(timestamp_str)
        return True
    except ValueError:
        return False

def authenticate(credentials):
    """Authenticate with Nobl9 API using credentials."""
    client_id = credentials.get("clientId")
    client_secret = credentials.get("clientSecret")
    if not client_id or not client_secret:
        print(f"{Fore.RED}ERROR: Missing credentials in context.{Style.RESET_ALL}")
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
            org_id = input(f"{Fore.CYAN}Enter Nobl9 Organization ID (find in Nobl9 UI under "
                          f"{Fore.CYAN}Settings > Account):{Style.RESET_ALL} ").strip()
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
            sys.exit(0)
    # Validate org_id
    if not org_id:
        print(f"{Fore.RED}ERROR: Organization ID is required.{Style.RESET_ALL}")
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
        print(f"{Fore.CYAN}API base url: {base_url}{Style.RESET_ALL}")
        # Use custom base URL for authentication
        auth_url = f"{base_url}/accessToken"
    else:
        auth_url = "https://app.nobl9.com/api/accessToken"
    
    try:
        response = requests.post(auth_url, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"{Fore.RED}ERROR: Authentication failed{Style.RESET_ALL}")
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
                                print(f"{Fore.RED}  Error Code: {nested_error.get('errorCode', 'Unknown')}{Style.RESET_ALL}")
                                print(f"{Fore.RED}  Summary: {nested_error.get('errorSummary', 'No summary provided')}{Style.RESET_ALL}")
                                print(f"{Fore.RED}  Error ID: {nested_error.get('errorId', 'No ID provided')}{Style.RESET_ALL}")
                                if nested_error.get('errorCauses'):
                                    print(f"{Fore.RED}  Causes: {nested_error['errorCauses']}{Style.RESET_ALL}")
                            else:
                                # If no JSON found, show the raw error string
                                print(f"{Fore.RED}  Error: {error_info}{Style.RESET_ALL}")
                        except json.JSONDecodeError:
                            # If nested parsing fails, show the raw error string
                            print(f"{Fore.RED}  Error: {error_info}{Style.RESET_ALL}")
                    else:
                        # Error is already a dictionary
                        print(f"{Fore.RED}  Error Code: {error_info.get('errorCode', 'Unknown')}{Style.RESET_ALL}")
                        print(f"{Fore.RED}  Summary: {error_info.get('errorSummary', 'No summary provided')}{Style.RESET_ALL}")
                        print(f"{Fore.RED}  Error ID: {error_info.get('errorId', 'No ID provided')}{Style.RESET_ALL}")
                        if error_info.get('errorCauses'):
                            print(f"{Fore.RED}  Causes: {error_info['errorCauses']}{Style.RESET_ALL}")
                elif "message" in error_data:
                    print(f"{Fore.RED}  Message: {error_data['message']}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}  Response: {response.text}{Style.RESET_ALL}")
            except json.JSONDecodeError:
                print(f"{Fore.RED}  Raw response: {response.text}{Style.RESET_ALL}")
            sys.exit(1)
        
        token_data = response.json()
        token = token_data.get("access_token")
        if not token:
            print(f"{Fore.RED}ERROR: No access token in response{Style.RESET_ALL}")
            print(f"  Response: {response.text}")
            sys.exit(1)
        return token, org_id
    except requests.exceptions.Timeout:
        print(f"{Fore.RED}ERROR: Authentication request timed out{Style.RESET_ALL}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}ERROR: Network error during authentication: {e}{Style.RESET_ALL}")
        sys.exit(1)
    except json.JSONDecodeError:
        print(f"{Fore.RED}ERROR: Invalid JSON response from authentication endpoint{Style.RESET_ALL}")
        print(f"  Response: {response.text}")
        sys.exit(1)

def fetch_annotations(token, org, start_time, end_time, is_custom_instance=False,
                     custom_base_url=None):
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
            print(f"{Fore.RED}ERROR: Start time is after end time{Style.RESET_ALL}")
            sys.exit(1)
    except ValueError as e:
        print(f"{Fore.RED}ERROR: Invalid timestamp format: {e}{Style.RESET_ALL}")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {token}",
        "Organization": org,
        "Accept": "application/json; version=v1alpha",
        "Project": "*"
    }
    
    print(f"\n{Fore.CYAN}Fetching annotations...{Style.RESET_ALL}")
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
            print(f"{Fore.RED}ERROR: API request failed (Status: {response.status_code}){Style.RESET_ALL}")
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
                                print(f"{Fore.RED}  Error Code: {nested_error.get('errorCode', 'Unknown')}{Style.RESET_ALL}")
                                print(f"{Fore.RED}  Summary: {nested_error.get('errorSummary', 'No summary provided')}{Style.RESET_ALL}")
                                print(f"{Fore.RED}  Error ID: {nested_error.get('errorId', 'No ID provided')}{Style.RESET_ALL}")
                            else:
                                # If no JSON found, show the raw error string
                                print(f"{Fore.RED}  Error: {error_info}{Style.RESET_ALL}")
                        except json.JSONDecodeError:
                            # If nested parsing fails, show the raw error string
                            print(f"{Fore.RED}  Error: {error_info}{Style.RESET_ALL}")
                    else:
                        # Error is already a dictionary
                        print(f"{Fore.RED}  Error Code: {error_info.get('errorCode', 'Unknown')}{Style.RESET_ALL}")
                        print(f"{Fore.RED}  Summary: {error_info.get('errorSummary', 'No summary provided')}{Style.RESET_ALL}")
                        print(f"{Fore.RED}  Error ID: {error_info.get('errorId', 'No ID provided')}{Style.RESET_ALL}")
                elif "message" in error_data:
                    print(f"{Fore.RED}  Message: {error_data['message']}{Style.RESET_ALL}")
                else:
                    print(f"{Fore.RED}  Response: {response.text}{Style.RESET_ALL}")
            except json.JSONDecodeError:
                print(f"{Fore.RED}  Raw response: {response.text}{Style.RESET_ALL}")
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
            print(f"{Fore.RED}ERROR: Unexpected response format: {type(data)}{Style.RESET_ALL}")
            sys.exit(1)
        
        print(f" {Fore.GREEN}Found {len(annotations)} annotations{Style.RESET_ALL}")
        
    except requests.exceptions.Timeout:
        print(f"{Fore.RED}ERROR: API request timed out{Style.RESET_ALL}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"{Fore.RED}ERROR: Network error during API request: {e}{Style.RESET_ALL}")
        sys.exit(1)
    except Exception as e:
        print(f"{Fore.RED}ERROR: Failed to fetch annotations: {e}{Style.RESET_ALL}")
        sys.exit(1)
    
    print(f"Annotation collection complete!{Style.RESET_ALL}")
    print(f"Total annotations retrieved: {len(annotations)}")
    
    # Sort annotations by timestamp
    annotations.sort(key=lambda x: x.get("startTime", ""), reverse=True)
    
    return annotations

def select_time_period():
    """Allow user to select time period for annotation filtering."""
    while True:
        print(f"\n{Fore.CYAN}Select time period:{Style.RESET_ALL}")
        print("  [1] Past 24 hours")
        print("  [2] Past 7 days")
        print("  [3] Past 14 days")
        print("  [4] Past 30 days")
        print("  [5] Specific day")
        print("  [6] Custom range")
        
        try:
            choice = input(f"{Fore.CYAN}Enter choice:{Style.RESET_ALL} ").strip()
            if not choice:
                print(f"{Fore.RED}ERROR: Please enter a choice.{Style.RESET_ALL}")
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
                    day = input(f"{Fore.CYAN}Enter date (YYYY-MM-DD):{Style.RESET_ALL} ").strip()
                    if validate_date_format(day):
                        start_time = f"{day}T00:00:00Z"
                        end_time = f"{day}T23:59:59Z"
                        return start_time, end_time
                    else:
                        print(f"{Fore.RED}ERROR: Invalid date format. Please use YYYY-MM-DD{Style.RESET_ALL}")
            elif choice == 6:
                while True:
                    start_time = input(f"{Fore.CYAN}Enter start time (YYYY-MM-DDThh:mm:ssZ):{Style.RESET_ALL} "
                                     f"").strip()
                    if validate_timestamp_format(start_time):
                        break
                    else:
                        print(f"{Fore.RED}ERROR: Invalid start time format. "
                              f"{Fore.RED}Please use YYYY-MM-DDThh:mm:ssZ{Style.RESET_ALL}")
                
                while True:
                    end_time = input(f"{Fore.CYAN}Enter end time (YYYY-MM-DDThh:mm:ssZ):{Style.RESET_ALL} "
                                   f"").strip()
                    if validate_timestamp_format(end_time):
                        break
                    else:
                        print(f"{Fore.RED}ERROR: Invalid end time format. "
                              f"{Fore.RED}Please use YYYY-MM-DDThh:mm:ssZ{Style.RESET_ALL}")
                
                return start_time, end_time
            else:
                print(f"{Fore.RED}ERROR: Invalid choice. Please enter a number between 1 and 6.{Style.RESET_ALL}")
                continue
        except ValueError:
            print(f"{Fore.RED}ERROR: Invalid input. Please enter a number.{Style.RESET_ALL}")
            continue
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
            sys.exit(0)

def analyze_annotation_types(annotations):
    """Analyze and display annotation types found."""
    type_counts = {}
    for annotation in annotations:
        annotation_type = annotation.get("category", "Unknown")
        type_counts[annotation_type] = type_counts.get(annotation_type, 0) + 1
    
    print(f"\n{Fore.CYAN}Annotation Types Found:{Style.RESET_ALL}")
    for annotation_type, count in sorted(type_counts.items()):
        print(f"  - {annotation_type}: {count} annotations")
    
    return type_counts

def select_annotation_types(available_types):
    """Allow user to select specific annotation types to view."""
    type_list = list(available_types.keys())
    
    while True:
        print(f"\n{Fore.CYAN}Select annotation types to view:{Style.RESET_ALL}")
        print("  [0] All annotation types")
        for i, annotation_type in enumerate(type_list, 1):
            count = available_types[annotation_type]
            print(f"  [{i}] {annotation_type} ({count} annotations)")
        print("  Or enter multiple numbers (comma-separated, e.g., 1,3,5)")
        
        try:
            choice = input(f"{Fore.CYAN}Enter choice:{Style.RESET_ALL} ").strip()
            
            # Handle "0" for all types
            if choice == "0":
                return set(type_list)  # Return all types
            
            # Handle comma-separated numbers
            if "," in choice:
                selected_numbers = [num.strip() for num in choice.split(",") 
                                 if num.strip()]
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
                            print(f"{Fore.RED}ERROR: Invalid number {num}. "
                                  f"{Fore.RED}Must be between 0 and {len(type_list)}{Style.RESET_ALL}")
                            continue
                    except ValueError:
                        print(f"{Fore.RED}ERROR: Invalid input '{num_str}'. Must be a number.{Style.RESET_ALL}")
                        continue
                
                # If 0 is included, return all types (ignore other numbers)
                if has_zero:
                    print(f"{Fore.YELLOW}Note: '0' (all types) selected - ignoring other numbers{Style.RESET_ALL}")
                    return set(type_list)
                
                if selected_types:
                    return selected_types
                else:
                    print(f"{Fore.RED}ERROR: No valid types selected.{Style.RESET_ALL}")
                    continue
            
            # Handle single number
            try:
                choice_num = int(choice)
                if 1 <= choice_num <= len(type_list):
                    return {type_list[choice_num-1]}  # Return selected type
                else:
                    print(f"{Fore.RED}ERROR: Invalid choice. Please enter a number between "
                          f"{Fore.RED}0 and {len(type_list)}, or comma-separated numbers.{Style.RESET_ALL}")
                    continue
            except ValueError:
                print(f"{Fore.RED}ERROR: Invalid input. Please enter a number or "
                      f"{Fore.RED}comma-separated numbers.{Style.RESET_ALL}")
                continue
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
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
    return (", ".join(slo_names) if slo_names else "None",
            ", ".join(project_names) if project_names else "None")

def display_annotations(annotations, selected_types):
    """Display annotations in a formatted table."""
    from tabulate import tabulate
    
    # Filter annotations by selected types
    filtered_annotations = [
        ann for ann in annotations 
        if ann.get("category", "Unknown") in selected_types
    ]
    
    if not filtered_annotations:
        print(f"\n{Fore.YELLOW}No annotations found for selected types: "
              f"{', '.join(selected_types)}{Style.RESET_ALL}")
        return
    
    # Format annotations for display
    rows = []
    for annotation in filtered_annotations:
        slos_display, projects_display = extract_slo_and_project_names(annotation)
        description = annotation.get("description", "")
        if len(description) > 50:
            description = description[:50] + "..."
        
        rows.append({
            "Time": format_timestamp(annotation.get("startTime", "")),
            "Type": annotation.get("category", ""),
            "Description": description,
            "SLOs": slos_display if slos_display else "None",
            "Projects": projects_display if projects_display else "None"
        })

    print(f"\n{Fore.CYAN}Annotation Table ({len(filtered_annotations)} annotations):{Style.RESET_ALL}")
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
        print(f"{Fore.RED}ERROR: Permission denied creating export directory{Style.RESET_ALL}")
        return
    except Exception as e:
        print(f"{Fore.RED}ERROR: Failed to create export directory: {e}{Style.RESET_ALL}")
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
            print(f"{Fore.GREEN}Exported to {base}.csv{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}ERROR: Failed to export CSV: {e}{Style.RESET_ALL}")
        
    elif export_format == "2":  # JSON (full details)
        try:
            with open(f"{base}.json", "w") as f:
                json.dump(annotations, f, indent=2)
            print(f"{Fore.GREEN}Exported to {base}.json{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}ERROR: Failed to export JSON: {e}{Style.RESET_ALL}")
        
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
            print(f"{Fore.GREEN}Exported to {base}.xlsx{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}ERROR: Failed to export Excel: {e}{Style.RESET_ALL}")

def main():
    """Main function for the Nobl9 Annotations Tool."""
    print(f"{Fore.CYAN}Nobl9 Annotations Tool{Style.RESET_ALL}")
    print("=" * 40)
    
    try:
        check_dependencies()
        context_name, credentials = enhanced_choose_context()
        
        token, org = authenticate(credentials)
        if not token or not org:
            print(f"{Fore.RED}ERROR: Authentication failed{Style.RESET_ALL}")
            sys.exit(1)
        
        # Get custom instance information from credentials
        is_custom_instance = credentials.get("is_custom_instance", False)
        custom_base_url = credentials.get("base_url")
        
        # Select time period
        start_time, end_time = select_time_period()
        
        # Fetch annotations
        annotations = fetch_annotations(token, org, start_time, end_time,
                                     is_custom_instance, custom_base_url)
        
        if not annotations:
            print(f"{Fore.YELLOW}No annotations found in the specified time range.{Style.RESET_ALL}")
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
                print(f"{Fore.YELLOW}No annotations found for selected types.{Style.RESET_ALL}")
                continue
            
            # Export options
            print(f"\n{Fore.CYAN}Export options:{Style.RESET_ALL}")
            print("  [1] CSV")
            print("  [2] JSON (full details)")
            print("  [3] Excel")
            print("  [Enter] Skip export")
            
            try:
                choice = input(f"\n{Fore.CYAN}Select export format:{Style.RESET_ALL} ").strip()
                if choice in ["1", "2", "3"]:
                    export_annotations(filtered_annotations, context_name, choice)
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
                sys.exit(0)
            
            # Ask if user wants to continue or exit
            print(f"\n{Fore.CYAN}Options:{Style.RESET_ALL}")
            print("  [1] Select different annotation types")
            print("  [2] Exit")
            
            try:
                continue_choice = input(f"{Fore.CYAN}Enter choice:{Style.RESET_ALL} ").strip()
                if continue_choice == "2":
                    print(f"{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
                    break
                elif continue_choice != "1":
                    print(f"{Fore.RED}Invalid choice. Continuing with type selection...{Style.RESET_ALL}")
            except KeyboardInterrupt:
                print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
                sys.exit(0)
            
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Exiting...{Style.RESET_ALL}")
        sys.exit(0)
    except Exception as e:
        print(f"{Fore.RED}ERROR: Unexpected error: {e}{Style.RESET_ALL}")
        sys.exit(1)

if __name__ == "__main__":
    main() 
    