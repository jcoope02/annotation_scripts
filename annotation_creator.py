#!/usr/bin/env python3
"""
Script name: annotation_creator.py

Purpose: Interactively create annotations in Nobl9 via the Annotations API.
Supports creating annotations for projects, services, or individual SLOs with
customizable descriptions and time ranges. Includes comprehensive logging.

Dependencies: requests, toml, yaml, subprocess, sloctl CLI
Compatible with: macOS and Linux

Author: Jeremy Cooper
Date Created: 2025-01-27
"""

import os
import sys
import json
import yaml
import toml
import shutil
import subprocess
import requests
import base64
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Color definitions for terminal output
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    NC = '\033[0m'  # No Color

def print_colored(text, color, end="\n"):
    """Print colored text to terminal."""
    print(f"{color}{text}{Colors.NC}", end=end)

def setup_logging():
    """Setup logging to a local file."""
    log_dir = Path("./annotation_logs")
    log_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"annotation_creator_{timestamp}.log"
    
    return log_file

def log_message(log_file, message, level="INFO"):
    """Log message to file with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {level}: {message}\n"
    
    with open(log_file, 'a') as f:
        f.write(log_entry)
    
    # Also print to console
    if level == "ERROR":
        print_colored(message, Colors.RED)
    elif level == "WARNING":
        print_colored(message, Colors.YELLOW)
    elif level == "SUCCESS":
        print_colored(message, Colors.GREEN)
    else:
        print_colored(message, Colors.CYAN)

def check_dependencies():
    """Check if required dependencies are available."""
    missing = []
    
    # Check Python packages
    try:
        import requests
    except ImportError:
        missing.append("requests")
    
    try:
        import yaml
    except ImportError:
        missing.append("PyYAML")
    
    try:
        import toml
    except ImportError:
        missing.append("toml")
    
    # Check sloctl CLI
    if not shutil.which("sloctl"):
        print_colored("ERROR: 'sloctl' is not installed or not in PATH.", Colors.RED)
        print_colored("You can install it from https://docs.nobl9.com/sloctl/", Colors.CYAN)
        sys.exit(1)
    
    if missing:
        print_colored("\nMissing required Python packages:", Colors.RED)
        for pkg in missing:
            print_colored(f"  - {pkg}", Colors.RED)
        print_colored("\nYou can install them using:", Colors.CYAN)
        print_colored(f"  pip3 install {' '.join(missing)}", Colors.CYAN)
        sys.exit(1)

def load_toml_config():
    """Load and parse TOML configuration with enhanced error handling."""
    config_path = os.path.expanduser("~/.config/nobl9/config.toml")
    if not os.path.isfile(config_path):
        print_colored(f"Config not found: {config_path}", Colors.RED)
        sys.exit(1)
    
    try:
        config = toml.load(config_path)
        return config
    except Exception as e:
        print_colored(f"Error loading TOML config: {e}", Colors.RED)
        sys.exit(1)

def load_contexts_from_toml():
    """Load contexts from TOML config with custom instance detection."""
    config = load_toml_config()
    contexts = []
    
    # Get the contexts section from the config
    raw_contexts = config.get("contexts", {})
    
    for context_name, context_data in raw_contexts.items():
        if isinstance(context_data, dict):
            # Check if this is a custom instance
            is_custom_instance = "url" in context_data
            base_url = context_data.get("url", "https://app.nobl9.com")
            
            # Handle both camelCase and snake_case field names
            client_id = context_data.get("clientId") or context_data.get("client_id", "")
            client_secret = context_data.get("clientSecret") or context_data.get("client_secret", "")
            org = context_data.get("organization") or context_data.get("org", "")
            access_token = context_data.get("accessToken", "")
            
            contexts.append({
                "name": context_name,
                "client_id": client_id,
                "client_secret": client_secret,
                "org": org,
                "access_token": access_token,
                "is_custom_instance": is_custom_instance,
                "base_url": base_url
            })
    
    return contexts

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
    except Exception as e:
        return None

def enhanced_choose_context():
    """Enhanced context selection with custom instance support."""
    contexts = load_contexts_from_toml()
    
    if not contexts:
        print_colored("No contexts found in TOML config.", Colors.RED)
        sys.exit(1)
    
    print_colored("\nAvailable contexts:", Colors.CYAN)
    for i, context in enumerate(contexts, 1):
        instance_info = f" (Custom: {context['base_url']})" if context['is_custom_instance'] else ""
        print(f"  [{i}] {context['name']}{instance_info}")
    
    while True:
        try:
            choice = input(f"\nSelect context [1-{len(contexts)}]: ").strip()
            if not choice:
                print_colored("Please enter a valid choice.", Colors.RED)
                continue
                
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(contexts):
                selected_context = contexts[choice_idx]
                
                # Set sloctl context
                result = subprocess.run(
                    ["sloctl", "config", "use-context", selected_context["name"]], 
                    capture_output=True, 
                    text=True
                )
                
                if result.returncode != 0:
                    print_colored(f"Warning: Could not set sloctl context: {result.stderr}", Colors.YELLOW)
                
                return selected_context["name"], selected_context
            else:
                print_colored(f"Invalid choice. Please enter a number between 1 and {len(contexts)}.", Colors.RED)
        except ValueError:
            print_colored("Invalid input. Please enter a number.", Colors.RED)
        except KeyboardInterrupt:
            print_colored("\nOperation cancelled.", Colors.CYAN)
            sys.exit(0)

def get_token_from_credentials(credentials, log_file):
    """Get access token using credentials with custom instance support."""
    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]
    org = credentials["org"]
    is_custom_instance = credentials.get("is_custom_instance", False)
    base_url = credentials.get("base_url", "https://app.nobl9.com")
    
    # Validate required credentials
    if not client_id or not client_secret:
        log_message(log_file, "ERROR: Missing client_id or client_secret in context.", "ERROR")
        sys.exit(1)
    
    # Try multiple sources for organization ID
    if not org and credentials.get("access_token"):
        org = decode_jwt_payload(credentials["access_token"])
    
    if not org:
        org = os.getenv("SLOCTL_ORGANIZATION")
    
    if not org:
        log_message(log_file, "ERROR: Missing organization in context. Please check your TOML configuration.", "ERROR")
        sys.exit(1)
    
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Accept": "application/json; version=v1alpha",
        "Organization": org,
        "Authorization": f"Basic {auth}"
    }
    
    token_url = f"{base_url}/api/accessToken"
    log_message(log_file, f"Authenticating with {token_url}", "INFO")
    
    resp = requests.post(token_url, headers=headers)
    
    if resp.status_code != 200:
        log_message(log_file, f"Failed to retrieve token. Status: {resp.status_code}", "ERROR")
        try:
            error_data = resp.json()
            if isinstance(error_data, dict):
                error_msg = error_data.get("message", "Unknown error")
            else:
                error_msg = str(error_data)
            log_message(log_file, f"Error: {error_msg}", "ERROR")
        except:
            log_message(log_file, f"Response: {resp.text}", "ERROR")
        sys.exit(1)
    
    try:
        token_data = resp.json()
        if "access_token" not in token_data:
            log_message(log_file, f"No access_token in response: {token_data}", "ERROR")
            sys.exit(1)
    except json.JSONDecodeError:
        log_message(log_file, f"Invalid JSON response: {resp.text}", "ERROR")
        sys.exit(1)
    
    log_message(log_file, "✓ Access token acquired", "SUCCESS")
    if is_custom_instance:
        log_message(log_file, f"Instance: {base_url}", "INFO")
    
    return token_data["access_token"], org, is_custom_instance, base_url

def fetch_slo_data(log_file):
    """Fetch SLO data from Nobl9."""
    log_message(log_file, "Fetching SLO data from Nobl9...", "INFO")
    
    try:
        result = subprocess.run(
            ["sloctl", "get", "slos", "-A", "-o", "json"],
            capture_output=True,
            text=True,
            check=True
        )
        slos_json = result.stdout.strip()
        
        # Validate JSON
        slos_data = json.loads(slos_json)
        if not isinstance(slos_data, list):
            log_message(log_file, "ERROR: Invalid SLO data format.", "ERROR")
            sys.exit(1)
        
        log_message(log_file, f"✓ Retrieved {len(slos_data)} SLOs", "SUCCESS")
        return slos_data
        
    except subprocess.CalledProcessError as e:
        log_message(log_file, f"ERROR: Failed to fetch SLO data: {e}", "ERROR")
        log_message(log_file, "Please check your Nobl9 configuration.", "INFO")
        sys.exit(1)
    except json.JSONDecodeError as e:
        log_message(log_file, f"ERROR: Invalid JSON response: {e}", "ERROR")
        sys.exit(1)

def get_valid_input(prompt, field_name, log_file):
    """Get valid user input."""
    while True:
        value = input(prompt).strip()
        if not value:
            log_message(log_file, f"{field_name} cannot be empty.", "WARNING")
        else:
            return value

def get_annotation_name(prompt, log_file):
    """Get annotation name and automatically sanitize it to valid format."""
    # Auto-generate UUID for annotation name
    annotation_uuid = str(uuid.uuid4())
    print_colored(f"Annotation UUID: {annotation_uuid}", Colors.GREEN)
    log_message(log_file, f"Generated annotation UUID: {annotation_uuid}", "INFO")
    return annotation_uuid
    
    # Manual input option (commented out for future use)
    # while True:
    #     original_name = input(prompt).strip()
    #     if not original_name:
    #         log_message(log_file, "Annotation name cannot be empty.", "WARNING")
    #         continue
    #     
    #     # Sanitize the name
    #     sanitized_name = sanitize_annotation_name(original_name)
    #     
    #     # If the name was changed, show the user
    #     if sanitized_name != original_name:
    #         print_colored(f"Original name: '{original_name}'", Colors.YELLOW)
    #         print_colored(f"Sanitized name: '{sanitized_name}'", Colors.GREEN)
    #             
    #         # Ask for confirmation
    #         confirm = input("Use this sanitized name? (y/n): ").strip().lower()
    #         if confirm in ['y', 'yes']:
    #         log_message(log_file, f"Using sanitized annotation name: '{sanitized_name}' (original: '{original_name}')", "INFO")
    #         return sanitized_name
    #         else:
    #         print_colored("Please enter a different name.", Colors.CYAN)
    #         continue
    #     else:
    #         # Name was already valid
    #         return sanitized_name

def get_time_input(prompt, log_file):
    """Get valid time input from user with improved validation and formatting."""
    while True:
        time_str = input(prompt).strip()
        
        # Clean up common formatting issues
        time_str = time_str.replace(' ', '')  # Remove spaces
        
        # Check for the specific error pattern from the API
        if '::' in time_str:
            log_message(log_file, "Invalid time format: double colon detected. Please use single colons only.", "WARNING")
            continue
        
        # Handle various timezone formats
        if time_str.endswith('Z'):
            # Ensure proper RFC3339 format for Z timezone
            if time_str.count(':') > 2:
                log_message(log_file, "Invalid time format: too many colons. Please use format: 2025-01-27T10:00:00Z", "WARNING")
                continue
            
            # Validate the format
            try:
                # Parse and reformat to ensure RFC3339 compliance
                dt = datetime.fromisoformat(time_str.replace('Z', '+00:00'))
                # Return in proper RFC3339 format
                return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            except ValueError:
                log_message(log_file, "Invalid time format. Please use ISO format (e.g., 2025-01-27T10:00:00Z)", "WARNING")
                continue
        else:
            # Handle other timezone formats
            try:
                datetime.fromisoformat(time_str)
                return time_str
            except ValueError:
                log_message(log_file, "Invalid time format. Please use ISO format with Z timezone (e.g., 2025-01-27T10:00:00Z)", "WARNING")
                continue

def format_timestamp_example():
    """Return a properly formatted timestamp example for user guidance."""
    now = datetime.now()
    return now.strftime('%Y-%m-%dT%H:%M:%SZ')

def sanitize_annotation_name(name):
    """Convert user input to a valid annotation name following DNS-1123 conventions."""
    import re
    
    # Convert to lowercase
    sanitized = name.lower()
    
    # Replace spaces, underscores, and other invalid characters with hyphens
    sanitized = re.sub(r'[^a-z0-9-]', '-', sanitized)
    
    # Remove multiple consecutive hyphens
    sanitized = re.sub(r'-+', '-', sanitized)
    
    # Remove leading and trailing hyphens
    sanitized = sanitized.strip('-')
    
    # Ensure it's not empty
    if not sanitized:
        sanitized = 'annotation'
    
    # Ensure it starts with a letter or number (not hyphen)
    if sanitized.startswith('-'):
        sanitized = 'a' + sanitized
    
    # Ensure it ends with a letter or number (not hyphen)
    if sanitized.endswith('-'):
        sanitized = sanitized + '1'
    
    return sanitized

def show_name_conversion_examples():
    """Show examples of name conversion for user guidance."""
    examples = [
        "Test Annotation",
        "my_annotation_name",
        "Production Deployment",
        "bug-fix-123",
        "Emergency Maintenance!"
    ]
    
    print_colored("\n📋 Name conversion examples:", Colors.CYAN)
    for example in examples:
        converted = sanitize_annotation_name(example)
        print_colored(f"   '{example}' → '{converted}'", Colors.WHITE)

def get_annotation_details(log_file):
    """Get annotation details from user input."""
    # Note: We don't generate UUID here anymore - it will be generated per SLO
    description = get_valid_input("Enter annotation description: ", "description", log_file)
    
    # Ask for link text (optional)
    link_text = input("Enter external hyperlink text (optional, press Enter to skip): ").strip()
    
    if link_text:
        link_url = input("Enter URL: ").strip()
        
        if link_url:
            # Add the link in Markdown format to the description
            markdown_link = f"\n\n[{link_text}]({link_url})"
            description += markdown_link
            print_colored(f"✓ Added link: [{link_text}]({link_url})", Colors.GREEN)
            log_message(log_file, f"Added Markdown link to description: [{link_text}]({link_url})", "INFO")
        else:
            print_colored("⚠ URL is required when link text is provided. Skipping link addition.", Colors.YELLOW)
    
    example_time = format_timestamp_example()
    start_time = get_time_input(f"Enter start time (ISO format, e.g., {example_time}): ", log_file)
    end_time = get_time_input(f"Enter end time (ISO format, e.g., {example_time}): ", log_file)
    
    return description, start_time, end_time

def create_annotations_for_slos(slos_list, description, start_time, end_time, 
                               access_token, org, is_custom_instance, base_url, log_file):
    """Create annotations for a list of SLOs with unique UUIDs for each."""
    success_count = 0
    total_count = len(slos_list)
    
    log_message(log_file, f"Creating annotations for {total_count} SLOs", "INFO")
    
    for slo in slos_list:
        slo_name = slo.get('metadata', {}).get('name')
        slo_project = slo.get('metadata', {}).get('project')
        
        if slo_name and slo_project:
            # Generate unique UUID for each annotation
            annotation_uuid = str(uuid.uuid4())
            print_colored(f"Creating annotation {annotation_uuid} for SLO '{slo_name}'", Colors.CYAN)
            
            annotation_data = {
                "name": annotation_uuid,
                "description": description,
                "startTime": start_time,
                "endTime": end_time,
                "project": slo_project,
                "slo": slo_name
            }
            
            if create_annotation(annotation_data, access_token, org, is_custom_instance, base_url, log_file):
                success_count += 1
    
    log_message(log_file, f"Annotation creation complete: {success_count}/{total_count} successful", "SUCCESS")
    return success_count, total_count

def create_annotation(annotation_data, access_token, org, is_custom_instance, base_url, log_file):
    """Create a single annotation via the Nobl9 API."""
    headers = {
        "Accept": "application/json; version=v1alpha",
        "Organization": org,
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    api_url = f"{base_url}/api/annotations" if is_custom_instance else "https://app.nobl9.com/api/annotations"
    
    try:
        response = requests.post(api_url, headers=headers, json=annotation_data)
        
        if response.status_code == 200:
            log_message(log_file, f"✓ Created annotation '{annotation_data['name']}' for SLO '{annotation_data['slo']}'", "SUCCESS")
            return True
        elif response.status_code == 409:
            log_message(log_file, f"⚠ Annotation '{annotation_data['name']}' already exists for SLO '{annotation_data['slo']}'", "WARNING")
            return False
        else:
            log_message(log_file, f"✗ Failed to create annotation '{annotation_data['name']}' for SLO '{annotation_data['slo']}'. Status: {response.status_code}", "ERROR")
            try:
                error_data = response.json()
                log_message(log_file, f"Error details: {error_data}", "ERROR")
            except:
                log_message(log_file, f"Response: {response.text}", "ERROR")
            return False
            
    except Exception as e:
        log_message(log_file, f"✗ Exception creating annotation '{annotation_data['name']}' for SLO '{annotation_data['slo']}': {e}", "ERROR")
        return False

def list_projects(slos_data, access_token, org, is_custom_instance, base_url, log_file):
    """List projects and create annotations for selected project."""
    log_message(log_file, "\nProjects:", "INFO")
    
    # Extract unique projects
    projects = {}
    for slo in slos_data:
        project = slo.get('metadata', {}).get('project')
        if project:
            if project not in projects:
                projects[project] = []
            projects[project].append(slo)
    
    # Display projects with SLO counts
    project_list = list(projects.keys())
    
    if not project_list:
        print_colored("No projects found with SLOs.", Colors.YELLOW)
        return
    
    for i, project in enumerate(project_list, 1):
        count = len(projects[project])
        print(f"  [{i}] {project} ({Colors.GREEN}{count}{Colors.NC} SLOs)")
    
    # Get user selection
    while True:
        try:
            choice = int(input("Select a project by number: "))
            if 1 <= choice <= len(project_list):
                selected_project = project_list[choice - 1]
                break
            else:
                print_colored(f"Please enter a number between 1 and {len(project_list)}.", Colors.RED)
        except ValueError:
            print_colored("Please enter a valid number.", Colors.RED)
        except KeyboardInterrupt:
            print_colored("\nOperation cancelled.", Colors.CYAN)
            return
    
    log_message(log_file, f"Selected project: {selected_project}", "SUCCESS")
    
    # Get annotation details and create annotations
    description, start_time, end_time = get_annotation_details(log_file)
    create_annotations_for_slos(
        projects[selected_project], description, start_time, end_time,
        access_token, org, is_custom_instance, base_url, log_file
    )

def list_services(slos_data, access_token, org, is_custom_instance, base_url, log_file):
    """List services and create annotations for selected service."""
    log_message(log_file, "\nServices:", "INFO")
    
    # Extract unique services
    services = {}
    for slo in slos_data:
        service = slo.get('spec', {}).get('service')
        if service:
            if service not in services:
                services[service] = []
            services[service].append(slo)
    
    # Display services with SLO counts
    service_list = list(services.keys())
    
    if not service_list:
        print_colored("No services found with SLOs.", Colors.YELLOW)
        return
    
    for i, service in enumerate(service_list, 1):
        count = len(services[service])
        print(f"  [{i}] {service} ({Colors.GREEN}{count}{Colors.NC} SLOs)")
    
    # Get user selection
    while True:
        try:
            choice = int(input("Select a service by number: "))
            if 1 <= choice <= len(service_list):
                selected_service = service_list[choice - 1]
                break
            else:
                print_colored(f"Please enter a number between 1 and {len(service_list)}.", Colors.RED)
        except ValueError:
            print_colored("Please enter a valid number.", Colors.RED)
        except KeyboardInterrupt:
            print_colored("\nOperation cancelled.", Colors.CYAN)
            return
    
    log_message(log_file, f"Selected service: {selected_service}", "SUCCESS")
    
    # Get annotation details and create annotations
    description, start_time, end_time = get_annotation_details(log_file)
    create_annotations_for_slos(
        services[selected_service], description, start_time, end_time,
        access_token, org, is_custom_instance, base_url, log_file
    )

def list_individual_slos(slos_data, access_token, org, is_custom_instance, base_url, log_file):
    """List individual SLOs and create annotations for selected ones."""
    log_message(log_file, "\nIndividual SLOs:", "INFO")
    
    # Display SLOs with project and service info
    for i, slo in enumerate(slos_data, 1):
        slo_name = slo.get('metadata', {}).get('name', 'Unknown')
        slo_project = slo.get('metadata', {}).get('project', 'Unknown')
        slo_service = slo.get('spec', {}).get('service', 'Unknown')
        print(f"  [{i}] {slo_name} (Project: {slo_project}, Service: {slo_service})")
    
    # Get user selection
    print_colored("\nEnter SLO numbers separated by commas (e.g., 1,3,5): ", Colors.CYAN)
    while True:
        try:
            choice_input = input().strip()
            selected_indices = [int(x.strip()) - 1 for x in choice_input.split(',')]
            
            # Validate indices
            valid_indices = [i for i in selected_indices if 0 <= i < len(slos_data)]
            if valid_indices:
                selected_slos = [slos_data[i] for i in valid_indices]
                break
            else:
                log_message(log_file, "Invalid SLO selection. Please try again.", "WARNING")
        except ValueError:
            log_message(log_file, "Invalid input. Please enter numbers separated by commas.", "WARNING")
    
    log_message(log_file, f"Selected {len(selected_slos)} SLOs", "SUCCESS")
    
    # Get annotation details and create annotations
    description, start_time, end_time = get_annotation_details(log_file)
    create_annotations_for_slos(
        selected_slos, description, start_time, end_time,
        access_token, org, is_custom_instance, base_url, log_file
    )

def main():
    """Main function."""
    print_colored("Nobl9 Annotation Creator", Colors.CYAN)
    print_colored("=" * 40, Colors.CYAN)
    
    # Show format guidance
    example_time = format_timestamp_example()
    print_colored(f"\n📝 Note: Timestamps should be in RFC3339 format (e.g., {example_time})", Colors.YELLOW)
    print_colored("   Avoid extra colons or spaces in your timestamps.", Colors.YELLOW)
    print_colored("📝 Note: Each annotation will get a unique UUID", Colors.YELLOW)
    print_colored("   (ensures uniqueness across all SLOs)", Colors.YELLOW)
    
    # Show name conversion examples (commented out since we use UUIDs now)
    # show_name_conversion_examples()
    
    # Setup logging
    log_file = setup_logging()
    log_message(log_file, "Annotation Creator started", "INFO")
    
    # Check dependencies
    check_dependencies()
    
    # Get context and authenticate
    context_name, credentials = enhanced_choose_context()
    log_message(log_file, f"Selected context: {context_name}", "INFO")
    
    access_token, org, is_custom_instance, base_url = get_token_from_credentials(credentials, log_file)
    
    # Fetch SLO data
    slos_data = fetch_slo_data(log_file)
    
    # Main menu loop
    while True:
        print_colored("\nMain Menu:", Colors.CYAN)
        print_colored("Choose how to apply annotations:", Colors.YELLOW)
        print("  [1] Apply to all SLOs in a Project")
        print("  [2] Apply to all SLOs in a Service")
        print("  [3] Apply to selected individual SLOs")
        print("  [x] Exit")
        
        try:
            choice = input("Select an option: ").strip().lower()
            
            if choice == "1":
                list_projects(slos_data, access_token, org, is_custom_instance, base_url, log_file)
            elif choice == "2":
                list_services(slos_data, access_token, org, is_custom_instance, base_url, log_file)
            elif choice == "3":
                list_individual_slos(slos_data, access_token, org, is_custom_instance, base_url, log_file)
            elif choice == "x":
                log_message(log_file, "Annotation Creator completed", "INFO")
                print_colored("Goodbye!", Colors.CYAN)
                sys.exit(0)
            else:
                print_colored("Invalid option. Please select 1, 2, 3, or x.", Colors.RED)
        except KeyboardInterrupt:
            print_colored("\nScript interrupted. Exiting.", Colors.RED)
            sys.exit(1)

if __name__ == "__main__":
    main() 