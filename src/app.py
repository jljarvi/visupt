import json
from datetime import datetime, timezone, timedelta
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import re
import os  # Added to check if file exists


def parse_hetrix_log(file_path):
    """Loads JSON data from the specified file."""
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Check if the expected structure is present
        if "messages" not in data:
            print(f"Error: 'messages' key not found in {file_path}")
            return None
        return data["messages"]
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {file_path}")
        return None
    except Exception as e:
        print(f"An error occurred while reading {file_path}: {e}")
        return None


def extract_events(messages):
    """Extracts service status events (UP/DOWN) and timestamps from messages."""
    if messages is None:
        return []

    events = []
    # Regex for "Target: [link text]" or "Target: plain text"
    target_regex = re.compile(
        r"Target:\s*(?:.*?\"type\":\s*\"link\",\s*\"text\":\s*\"([^\"]+)\"|([^\n]+))"
    )
    # Regex to extract service name from bold title (e.g., "Service Name is now UP")
    title_regex = re.compile(
        r"^(.*?)\s+(?:is now UP|is now DOWN|is still DOWN)", re.IGNORECASE
    )  # Added IGNORECASE

    for msg in messages:
        # Ensure message has the expected structure
        if (
            not isinstance(msg, dict)
            or msg.get("from") != "HetrixTools"
            or "text_entities" not in msg
            or "date_unixtime" not in msg
        ):
            continue  # Skip messages that don't fit the expected format

        try:
            timestamp = int(msg["date_unixtime"])
            dt_object = datetime.fromtimestamp(timestamp, timezone.utc)
        except (ValueError, TypeError):
            continue  # Skip if timestamp is invalid

        status = None
        target = None
        bold_text_content = None  # Store the content of the relevant bold entity
        text_content = ""

        # --- Build combined text content for easier searching ---
        raw_text = msg.get("text", "")
        if isinstance(raw_text, list):
            for item in raw_text:
                if isinstance(item, dict) and "text" in item:
                    text_content += str(item["text"]) + "\n"  # Ensure text is string
                elif isinstance(item, str):
                    text_content += item + "\n"
        elif isinstance(raw_text, str):
            text_content = raw_text
        else:
            continue  # Skip if text format is unexpected

        # --- Determine status (UP/DOWN) based on bold text ---
        text_entities = msg.get("text_entities", [])
        if not isinstance(text_entities, list):
            continue  # Skip if text_entities format is unexpected

        for entity in text_entities:
            if isinstance(entity, dict) and entity.get("type") == "bold":
                current_bold_text = entity.get("text", "")
                if "is now UP" in current_bold_text:
                    status = "UP"
                    bold_text_content = current_bold_text
                    break
                elif "is now DOWN" in current_bold_text:
                    status = "DOWN"
                    bold_text_content = current_bold_text
                    break
                elif "is still DOWN" in current_bold_text:
                    status = "DOWN"
                    bold_text_content = current_bold_text
                    break  # No need to check further entities for status

        # --- Find the target service (prioritise bold title, then Target line, then link) ---
        # Method 1 (Priority): Try parsing the bold title text
        if status and bold_text_content:
            title_match = title_regex.match(bold_text_content)
            if title_match:
                target = title_match.group(
                    1
                ).strip()  # Extract name before " is now..."

        # Method 2 (Fallback): Try regex on "Target: " line if title didn't yield target
        if target is None and status:
            match = target_regex.search(text_content)
            if match:
                target = match.group(1) or match.group(2)  # Link text or plain text
                if target:
                    target = target.strip()

        # Method 3 (Fallback): Fallback to first 'link' entity if still no target
        if target is None and status:
            for entity in text_entities:
                if isinstance(entity, dict) and entity.get("type") == "link":
                    potential_target_text = entity.get("text", "")
                    if (
                        "." in potential_target_text
                        and " " not in potential_target_text
                    ):
                        target = potential_target_text.strip()
                        break  # Take the first suitable link

        # --- Clean up and store event ---
        if target and status:
            # *** NEW: Remove trailing slash from the target name ***
            target = target.rstrip("/")
            # Ensure target is a simple string, remove extra spaces
            target = re.sub(r"\s+", " ", str(target)).strip()
            if target:  # Ensure target is not empty after stripping
                events.append({"service": target, "status": status, "time": dt_object})

    # Sort events chronologically
    events.sort(key=lambda x: x["time"])
    return events


def create_gantt_chart(events, selected_services, output_filename="uptime_gantt.png"):
    """Creates and saves a Gantt chart visualization."""
    # Filter events for selected services only
    # Ensure comparison is case-insensitive and handles stripped names
    # Convert selected services to lower case set for efficient lookup
    selected_services_set_lower = {s.strip().rstrip('/').lower() for s in selected_services}
    filtered_events = [
        e for e in events if e.get('service', '').lower() in selected_services_set_lower
    ]

    if not filtered_events:
        print("\nNo events found for the selected services. Cannot generate chart.")
        return

    # --- Plotting setup ---
    # Use the validated service names from the filtered events for plotting
    services_with_data = sorted(list(set(e['service'] for e in filtered_events)))
    print(f"\nGenerating Gantt chart for: {', '.join(services_with_data)}")

    if not services_with_data:
        print("Filtered list resulted in no services with data.")
        return

    fig, ax = plt.subplots(
        figsize=(18, len(services_with_data) * 0.6 + 2)
    )  # Dynamic height, slightly more padding
    y_labels = services_with_data
    y_ticks = range(len(y_labels))
    ax.set_yticks(y_ticks)
    ax.set_yticklabels(y_labels)
    ax.set_ylim(-0.5, len(y_labels) - 0.5)
    ax.invert_yaxis()  # Show first service at the top

    # Determine overall time range from filtered events
    min_time = min(e["time"] for e in filtered_events)
    max_time = max(e["time"] for e in filtered_events)
    # Add padding for better visualization
    time_diff = max_time - min_time
    padding = time_diff * 0.02  # Add 2% padding on each side
    if padding < timedelta(minutes=5):  # Ensure minimum padding
        padding = timedelta(minutes=5)
    plot_start_time = min_time - padding
    plot_end_time = max_time + padding
    ax.set_xlim(plot_start_time, plot_end_time)

    # --- Process and plot intervals for each service ---
    for i, service in enumerate(y_labels):
        # Get events for this specific service, already sorted by time
        service_events = [e for e in filtered_events if e["service"] == service]

        # Determine initial state (before first event) - assume UP unless first event is UP
        first_event = service_events[0]
        last_time = (
            plot_start_time  # Start plotting from the beginning of the chart range
        )
        last_status = (
            "DOWN" if first_event["status"] == "UP" else "UP"
        )  # Assume opposite state initially

        for event in service_events:
            current_time = event["time"]
            current_status = event[
                "status"
            ]  # This is the status *after* the event time

            if current_time > last_time:  # Ensure time has progressed
                # Plot the bar for the state *before* this event
                colour = "mediumseagreen" if last_status == "UP" else "lightcoral"
                # Ensure width is positive
                bar_width = current_time - last_time
                if bar_width > timedelta(0):
                    ax.barh(
                        i,
                        width=bar_width,
                        left=last_time,
                        height=0.6,
                        color=colour,
                        alpha=0.8,
                        edgecolor="grey",
                        linewidth=0.5,
                    )

            # Update status for the next interval
            last_status = current_status
            last_time = current_time

        # Plot the state from the last event until the end of the chart range
        if plot_end_time > last_time:
            colour = "mediumseagreen" if last_status == "UP" else "lightcoral"
            bar_width = plot_end_time - last_time
            if bar_width > timedelta(0):
                ax.barh(
                    i,
                    width=bar_width,
                    left=last_time,
                    height=0.6,
                    color=colour,
                    alpha=0.8,
                    edgecolor="grey",
                    linewidth=0.5,
                )

    # --- Formatting ---
    ax.xaxis_date()  # Treat x-axis as dates
    date_format = mdates.DateFormatter("%Y-%m-%d %H:%M")  # Format date/time labels
    ax.xaxis.set_major_formatter(date_format)
    # Auto-adjust number of ticks based on time range
    locator = mdates.AutoDateLocator(minticks=5, maxticks=12)
    ax.xaxis.set_major_locator(locator)

    plt.xticks(rotation=30, ha="right")  # Rotate labels for better readability
    plt.xlabel("Time (UTC)", fontsize=10)
    plt.ylabel("Service", fontsize=10)
    plt.title("Service Uptime/Downtime Gantt Chart", fontsize=12, fontweight="bold")
    plt.grid(axis="x", linestyle=":", alpha=0.7, color="grey")
    # Add legend
    legend_elements = [
        plt.Rectangle((0, 0), 1, 1, color="mediumseagreen", label="UP"),
        plt.Rectangle((0, 0), 1, 1, color="lightcoral", label="DOWN"),
    ]
    ax.legend(handles=legend_elements, loc="upper right", fontsize=9)

    plt.tight_layout(rect=[0, 0, 1, 0.97])  # Adjust layout, leave space for title

    # Save the chart
    try:
        plt.savefig(output_filename, dpi=200, bbox_inches="tight")
        print(f"\nSuccess! Gantt chart saved to {output_filename}")
    except Exception as e:
        print(f"\nError saving chart: {e}")

    # Optionally display the chart (uncomment if running locally)
    plt.show()


# --- Main Execution ---
if __name__ == "__main__":
    # --- Configuration ---
    json_file_path = "./input/hetrixtools.json"

    # List the exact service names (targets) you want to include in the chart.
    # Check the 'Detected Services' output below to see available names.
    # Example: services_to_plot = ['vw.nfld.uk', 'matrix.nfld.uk']
    services_to_plot = ["doccano", "staffcounter"]

    output_image_file = "output/service_uptime_gantt.png"  # Name for the output image

    # --- Processing ---
    all_messages = parse_hetrix_log(json_file_path)

    if all_messages:
        all_events = extract_events(all_messages)

        if not all_events:
            print("No valid UP/DOWN events could be extracted from the file.")
        else:
            # --- List detected services to help user choose ---
            all_detected_services = sorted(list(set(e["service"] for e in all_events)))
            print("-" * 30)
            print("Detected Services in Log (Original Case):") # Display original case
            if not all_detected_services:
                print(" (None found)")
            else:
                for s in all_detected_services:
                    print(f"- {s}")
            print("-" * 30)

             # --- Validate user's service list (case-insensitive, slash-stripped comparison) ---
            if not services_to_plot:
                print("\nError: No services specified in the 'services_to_plot' list.")
                print("Please edit the script and add the service names you want to plot.")
            else:
                # Normalise user input and detected services for case-insensitive comparison
                # Map lower-case user input to original user input for reporting
                user_services_map_lower_to_original = {
                    s.strip().rstrip('/').lower(): s for s in services_to_plot
                }
                # Create a lower-case set of detected service names
                detected_services_set_lower = {s.lower() for s in all_detected_services}

                # Find which user-provided services (lower case) are valid (exist in detected lower set)
                valid_services_lower = {
                    s_lower for s_lower in user_services_map_lower_to_original
                    if s_lower in detected_services_set_lower
                }
                # Find original user inputs that correspond to invalid lower-case names
                invalid_services_original = [
                    user_services_map_lower_to_original[s_lower]
                    for s_lower in user_services_map_lower_to_original
                    if s_lower not in detected_services_set_lower
                ]

                if invalid_services_original:
                    print("\nWarning: The following specified services were not found in the log data (case-insensitive search) and will be ignored:")
                    for s in sorted(invalid_services_original): # Sort original user input
                        print(f"- {s}")

                if valid_services_lower:
                    # Filter the *original* user list to get services that were found (case-insensitively)
                    # This preserves the user's intended capitalisation for the function call,
                    # though the function itself also performs case-insensitive filtering.
                    services_for_charting = [
                        s for s in services_to_plot
                        if s.strip().rstrip('/').lower() in valid_services_lower
                    ]
                    create_gantt_chart(all_events, services_for_charting, output_image_file)
                else:
                    # Check if there were *any* user services provided, even if invalid
                    if services_to_plot:
                        print("\nError: None of the specified services were found in the log data (case-insensitive search). No chart generated.")
                    # else: the error about no services being specified was already printed
