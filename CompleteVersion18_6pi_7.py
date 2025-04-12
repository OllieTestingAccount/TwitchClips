import requests
import datetime
import subprocess
import os
import shutil
import json
import cv2
import numpy as np
import time
import pickle
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import schedule
import logging
#from datetime import datetime, timedelta
import sys
import time as time_module
import threading

# YouTube API configuration
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

class ChannelManager:
    def __init__(self):
        self.video_counts_file = "channel_video_counts.json"
        self.schedule_file = "channel_schedules.json"
        self.load_data()

    def load_data(self):
        # Load video counts
        if os.path.exists(self.video_counts_file):
            with open(self.video_counts_file, 'r') as f:
                self.video_counts = json.load(f)
        else:
            self.video_counts = {}

        # Load schedules
        if os.path.exists(self.schedule_file):
            with open(self.schedule_file, 'r') as f:
                self.schedules = json.load(f)
        else:
            self.schedules = {}

    def save_data(self):
        with open(self.video_counts_file, 'w') as f:
            json.dump(self.video_counts, f)
        with open(self.schedule_file, 'w') as f:
            json.dump(self.schedules, f)

    def increment_video_count(self, channel):
        if channel not in self.video_counts:
            self.video_counts[channel] = 0
        self.video_counts[channel] += 1
        self.save_data()
        return self.video_counts[channel]

    def get_schedule_time(self, channel):
        return self.schedules.get(channel)

    def set_schedule_time(self, channel, time_str):
        self.schedules[channel] = time_str
        self.save_data()

def get_access_token(client_id, client_secret):
    url = "https://id.twitch.tv/oauth2/token"
    payload = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()['access_token']

def get_user_id(channel_name, client_id, access_token):
    url = f"https://api.twitch.tv/helix/users?login={channel_name}"
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    if data['data']:
        return data['data'][0]['id']
    else:
        raise ValueError("Channel not found.")

def get_top_clips(user_id, client_id, access_token):
    url = "https://api.twitch.tv/helix/clips"
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {access_token}'
    }

    end_time = datetime.datetime.utcnow()
    start_time = end_time - datetime.timedelta(days=7)

    params = {
        'broadcaster_id': user_id,
        'started_at': start_time.isoformat() + 'Z',
        'ended_at': end_time.isoformat() + 'Z',
        'first': 100
    }

    clips = []
    while True:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()

        if not data['data']:
            break

        for clip in data['data']:
            clips.append({
                'slug': clip['id'],
                'title': clip['title'],
                'view_count': clip['view_count']
            })

        if len(clips) >= 10:
            clips = clips[:10]
            break

        if 'pagination' in data and 'cursor' in data['pagination']:
            params['after'] = data['pagination']['cursor']
        else:
            break

    # Sort clips by view count in ascending order
    clips.sort(key=lambda x: x['view_count'])
    return clips

def download_clips(clips, output_dir):
    """
    Downloads Twitch clips using yt-dlp with improved error handling and debugging
    """
    downloaded_files = []
    os.makedirs(output_dir, exist_ok=True)

    print(f"Attempting to download {len(clips)} clips...")

    for index, clip in enumerate(clips, 1):
        clip_url = f"https://clips.twitch.tv/{clip['slug']}"
        output_path = os.path.join(output_dir, f"{index:02d}.mp4")
        
        print(f"\nDownloading clip {index}/{len(clips)}")
        print(f"URL: {clip_url}")
        print(f"Output path: {output_path}")
        
        command = [
            "yt-dlp",
            clip_url,
            "-o", output_path,
            "--force-overwrites",
            "-v"  # Verbose output for debugging
        ]
        
        try:
            # Check if yt-dlp is installed
            subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True)
        except FileNotFoundError:
            print("Error: yt-dlp is not installed. Installing now...")
            try:
                # Try to install yt-dlp using pip
                subprocess.run([sys.executable, "-m", "pip", "install", "yt-dlp"], check=True)
                print("yt-dlp installed successfully!")
            except subprocess.CalledProcessError as e:
                print(f"Failed to install yt-dlp: {e}")
                print("Please install yt-dlp manually using: pip install yt-dlp")
                return []
        
        try:
            result = subprocess.run(command, capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(output_path):
                # Check if the downloaded file is valid and has content
                if os.path.getsize(output_path) > 0:
                    downloaded_files.append(output_path)
                    print(f"Successfully downloaded clip {index}")
                else:
                    print(f"Error: Downloaded file is empty for clip {index}")
                    print(f"Standard output: {result.stdout}")
                    print(f"Standard error: {result.stderr}")
            else:
                print(f"Error downloading clip {index}")
                print(f"Return code: {result.returncode}")
                print(f"Standard output: {result.stdout}")
                print(f"Standard error: {result.stderr}")
                
        except subprocess.CalledProcessError as e:
            print(f"Error running yt-dlp for clip {index}: {e}")
            print(f"Standard output: {e.stdout}")
            print(f"Standard error: {e.stderr}")
        except Exception as e:
            print(f"Unexpected error downloading clip {index}: {e}")
    
    print(f"\nDownload summary:")
    print(f"Total clips attempted: {len(clips)}")
    print(f"Successfully downloaded: {len(downloaded_files)}")
    
    if len(downloaded_files) > 0:
        downloaded_files.sort(key=lambda x: int(os.path.splitext(os.path.basename(x))[0]))
        return downloaded_files
    else:
        print("\nNo clips were successfully downloaded. Possible issues:")
        print("1. Check if the clips are still available")
        print("2. Verify your internet connection")
        print("3. Make sure yt-dlp is properly installed")
        print("4. Check if you have write permissions in the output directory")
        return []

def get_video_info(video_file):
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        video_file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    
    r_frame_rate = data['streams'][0]['r_frame_rate'].split('/')
    fps = float(r_frame_rate[0]) / float(r_frame_rate[1])
    
    return {
        'width': int(data['streams'][0]['width']),
        'height': int(data['streams'][0]['height']),
        'fps': fps
    }

def get_video_duration(video_file):
    """Get the duration of a video file in seconds"""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_entries",
        "format=duration",
        video_file
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    data = json.loads(result.stdout)
    return float(data['format']['duration'])

def format_timestamp(seconds):
    """Convert seconds to MM:SS format"""
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)
    return f"{minutes}:{seconds:02d}"

def create_video_description(clips, video_files, channel_name):
    """Create a formatted video description with timestamps and clip links"""
    # Initial description
    description = f"The top clips from {channel_name}'s Twitch channel this week!"
    
    # Add blank lines
    description += "\n\n"
    
    # Add clip links
    description += "Clip Links-\n"
    for i, clip in enumerate(clips, 1):
        clip_url = f"https://clips.twitch.tv/{clip['slug']}"
        description += f"#{11-i} {clip_url}\n"

    #print(description)
    #logging.info(description)
    
    # Add blank lines
    description += "\n"
    
    # Calculate and add timestamps
    description += "Timestamps-\n"
    
    # Calculate duration of intro and transition
    TRANSITION_DURATION = 5  # Duration of transitions in seconds
    current_time = 0
    
    # Account for intro and first transition
    current_time += TRANSITION_DURATION * 2  # Pre-roll and first clip number transition
    
    # Create a list to store clip start times
    clip_times = []
    
    # Calculate start time for each clip
    for i, video_file in enumerate(video_files):
        clip_duration = get_video_duration(video_file)
        clip_times.append(current_time)
        current_time += clip_duration
        if i < len(video_files) - 1:
            current_time += TRANSITION_DURATION  # Add transition time between clips
    
    # Add timestamps in reverse order (10 to 1)
    for i in range(len(clip_times)):
        clip_number = len(clip_times) - i
        timestamp = format_timestamp(clip_times[i])
        description += f"{timestamp} #{clip_number}\n"
    
    return description

def create_text_transition(text, width, height, duration, fps, output_file):
    frames_dir = os.path.join(os.path.dirname(output_file), "transition_frames")
    os.makedirs(frames_dir, exist_ok=True)
    
    try:
        total_frames = int(duration * fps)
        lines = text.split("\n")
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 8
        thickness = 20
        line_spacing = 100
        
        text_sizes = [cv2.getTextSize(line, font, font_scale, thickness)[0] for line in lines]
        total_text_height = sum(size[1] for size in text_sizes) + (len(lines) - 1) * line_spacing
        y_offset = (height - total_text_height) // 2
        
        text_positions = []
        for i, size in enumerate(text_sizes):
            x = (width - size[0]) // 2
            y = y_offset + size[1] + i * (size[1] + line_spacing)
            text_positions.append((x, y))
        
        for frame_num in range(total_frames):
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            progress = frame_num / total_frames
            alpha = 2 * min(progress, 1 - progress)
            color = (int(255 * alpha), int(255 * alpha), int(255 * alpha))
            
            for line, position in zip(lines, text_positions):
                cv2.putText(frame, line, position, font, font_scale, color, thickness)
            
            frame_path = os.path.join(frames_dir, f"frame_{frame_num:04d}.png")
            cv2.imwrite(frame_path, frame)

        silent_audio = os.path.join(os.path.dirname(output_file), "silent_audio.mp3")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(duration),
            silent_audio
        ], check=True)
        
        subprocess.run([
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", os.path.join(frames_dir, "frame_%04d.png"),
            "-i", silent_audio,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-preset", "medium",
            "-vsync", "cfr",
            "-video_track_timescale", str(int(fps * 1000)),
            output_file
        ], check=True)
        
    finally:
        shutil.rmtree(frames_dir, ignore_errors=True)
        if os.path.exists(silent_audio):
            os.remove(silent_audio)

def combine_videos_with_ffmpeg(video_files, output_file, channel_name, transition_duration=5):
    temp_dir = os.path.abspath("temp_videos")
    os.makedirs(temp_dir, exist_ok=True)

    try:
        video_info = get_video_info(video_files[0])
        width = video_info['width']
        height = video_info['height']
        fps = video_info['fps']

        print(f"Processing videos: {width}x{height} at {fps}fps")
        
        processed_clips = []
        total_clips = len(video_files)

        # Create intro
        intro_title = f"Top {total_clips}\n{channel_name}\nClips of\nthe week"
        pre_roll_file = os.path.join(temp_dir, "pre_roll.ts")
        create_text_transition(intro_title, width, height, transition_duration, fps, pre_roll_file)
        processed_clips.append(pre_roll_file)

        # Add first clip number transition after intro
        first_transition = os.path.join(temp_dir, "first_transition.ts")
        create_text_transition(f"Clip #{total_clips}", width, height, transition_duration, fps, first_transition)
        processed_clips.append(first_transition)
        
        for i, video_file in enumerate(video_files, 1):
            clip_number = total_clips - i + 1
            
            video_temp = os.path.join(temp_dir, f"video_{i}.ts")
            subprocess.run([
                "ffmpeg", "-y",
                "-i", video_file,
                "-vf", f"scale={width}:{height},fps=fps={fps}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-c:a", "aac",
                "-ar", "44100",
                "-ac", "2",
                "-strict", "-2",
                "-video_track_timescale", str(int(fps * 1000)),
                "-f", "mpegts",
                video_temp
            ], check=True)
            processed_clips.append(video_temp)
            
            if i < len(video_files):
                transition_file = os.path.join(temp_dir, f"transition_{i}.ts")
                create_text_transition(
                    f"Clip #{clip_number - 1}",
                    width, height, 
                    transition_duration, fps, transition_file
                )
                processed_clips.append(transition_file)

        end_transition_file = os.path.join(temp_dir, "end_transition.ts")
        create_text_transition(
            "Thanks For\nWatching",
            width, height, 
            transition_duration, fps, end_transition_file
        )
        processed_clips.append(end_transition_file)

        concat_file = os.path.join(temp_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for clip in processed_clips:
                f.write(f"file '{os.path.abspath(clip)}'\n")

        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_file
        ], check=True)
        
        print(f"Final video saved as {output_file}")

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def authenticate_youtube():
    """
    Authenticate with YouTube API with automatic token regeneration and error handling.
    Returns an authenticated YouTube API service object.
    """
    def create_new_credentials():
        """Helper function to create new credentials through OAuth flow"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                "client_secret_658757777748-674k92uh4iqsulfd7q8roqu99a5ka84t.apps.googleusercontent.com.json", 
                SCOPES
            )
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
            #creds = flow.run_local_server(port=0)
            #creds = flow.run_local_server(port=0, prompt='consent')
            # Save new credentials
            with open("token.pickle", "wb") as token_file:
                pickle.dump(creds, token_file)
            return creds
        except Exception as e:
            logging.error(f"Failed to create new credentials: {str(e)}")
            raise

    def refresh_existing_credentials(creds):
        """Helper function to refresh existing credentials"""
        try:
            creds.refresh(Request())
            # Save refreshed credentials
            with open("token.pickle", "wb") as token_file:
                pickle.dump(creds, token_file)
            return creds
        except Exception as e:
            logging.warning(f"Failed to refresh credentials: {str(e)}")
            return None

    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            creds = None
            # Load existing credentials if they exist
            if os.path.exists("token.pickle"):
                try:
                    with open("token.pickle", "rb") as token_file:
                        creds = pickle.load(token_file)
                except Exception as e:
                    logging.warning(f"Failed to load existing token: {str(e)}")
                    # If token file is corrupted, remove it
                    os.remove("token.pickle")
                    creds = None

            # Check if we need to refresh or create new credentials
            if not creds:
                logging.info("No existing credentials found. Creating new ones...")
                creds = create_new_credentials()
            elif not creds.valid:
                if creds.expired and creds.refresh_token:
                    logging.info("Refreshing expired credentials...")
                    creds = refresh_existing_credentials(creds)
                    if not creds:  # Refresh failed
                        logging.info("Refresh failed. Creating new credentials...")
                        creds = create_new_credentials()
                else:
                    logging.info("Invalid credentials. Creating new ones...")
                    creds = create_new_credentials()

            # Build and test the YouTube service
            youtube = build("youtube", "v3", credentials=creds)
            # Test the credentials with a simple API call
            youtube.channels().list(part="snippet", mine=True).execute()
            
            logging.info("YouTube authentication successful")
            return youtube

        except Exception as e:
            retry_count += 1
            logging.error(f"Authentication attempt {retry_count} failed: {str(e)}")
            
            # If token.pickle exists, remove it before retry
            if os.path.exists("token.pickle"):
                os.remove("token.pickle")
                logging.info("Removed existing token.pickle file")

            if retry_count >= max_retries:
                logging.error("Max retries reached. Authentication failed.")
                raise Exception("Failed to authenticate with YouTube after maximum retry attempts")
            
            # Wait before retrying (exponential backoff)
            wait_time = 2 ** retry_count
            logging.info(f"Waiting {wait_time} seconds before retry...")
            time.sleep(wait_time)

def upload_to_youtube(youtube, video_file, channel_name, video_number, scheduled_time, clips, video_files):
    title = f"Top 10 {channel_name} Clips Of The Week #{video_number}"
    description = create_video_description(clips, video_files, channel_name)
    tags = [channel_name, "twitch", "clips", "highlights", "gaming"]
    
    publish_time = datetime.datetime.strptime(scheduled_time, "%H:%M")
    now = datetime.datetime.utcnow()

    publish_time = datetime.datetime(
        year=now.year,
        month=now.month,
        day=now.day,
        hour=publish_time.hour,
        minute=publish_time.minute
    )
    
    if publish_time <= now:
        publish_time += datetime.timedelta(days=1)

    request_body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_time.isoformat() + "Z"
        }
    }

    media_file = MediaFileUpload(video_file, chunksize=-1, resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=request_body,
        media_body=media_file
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Uploaded {int(status.progress() * 100)}%")

    print("Upload complete!")
    print(f"Video will go live at {publish_time} UTC")
    return response['id']

class ChannelScheduler:
    def __init__(self):
        self.schedule_file = "channel_schedules.json"
        self.client_id = "w4qeait6mrz9ufwnnaiz0qifv2fakg"
        self.client_secret = "9r34cfj51i0n816sgondtsaw8wwrdo"
        self.load_schedules()
        self.setup_logging()

    def setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('twitch_clips.log'),
                logging.StreamHandler(sys.stdout)
            ]
        )

    def load_schedules(self):
        """Load channel schedules from JSON file"""
        try:
            with open(self.schedule_file, 'r') as f:
                self.schedules = json.load(f)
        except FileNotFoundError:
            self.schedules = {}
            self.save_schedules()
        
    def save_schedules(self):
        """Save channel schedules to JSON file"""
        with open(self.schedule_file, 'w') as f:
            json.dump(self.schedules, f, indent=4)

    def add_channel(self, channel_name, upload_time, upload_days):
        """
        Add or update a channel's schedule
        
        Parameters:
        - channel_name: Twitch channel name
        - upload_time: Time to upload in HH:MM format (24-hour)
        - upload_days: List of days to upload (e.g., ["Monday", "Thursday"])
        """

        # Normalize upload days to lowercase for consistency
        normalized_days = [day.strip().lower() for day in upload_days]
        
        self.schedules[channel_name] = {
            "upload_time": upload_time,
            "upload_days": upload_days
        }
        self.save_schedules()
        self.schedule_channel(channel_name, upload_time, upload_days)
        logging.info(f"Added schedule for {channel_name}: {upload_time} on {', '.join(upload_days)}")

    def remove_channel(self, channel_name):
        """Remove a channel's schedule"""
        if channel_name in self.schedules:
            del self.schedules[channel_name]
            self.save_schedules()
            schedule.clear(channel_name)
            logging.info(f"Removed schedule for {channel_name}")

    def schedule_channel(self, channel_name, upload_time, upload_days):
        """Schedule a channel's uploads"""
        global last_run
        last_run = None
        
        def job():

            global last_run

            now = datetime.datetime.now()
            
            current_day = now.strftime('%A').lower()
            if current_day not in [day.lower() for day in upload_days]:
                #logging.info(f"Skipping job for {channel_name} on {current_day}. Scheduled for {upload_days}.")
                return
            
            if last_run and (now - last_run).total_seconds() < 60:
                logging.info(f"Stopped job running again for {channel_name}")
                return
            #last_run = now()
            
            try:
                logging.info(f"Starting job for {channel_name}")
                process_channel(channel_name, upload_time, self.client_id, self.client_secret)
                logging.info(f"Completed job for {channel_name}")
                last_run = datetime.datetime.now()
            except Exception as e:
                logging.error(f"Error processing {channel_name}: {str(e)}")
                last_run = datetime.datetime.now()
##            finally:
##                logging.info(f"Clearing job for {channel_name}")
##                logging.info(f"Jobs before clearing: {len(schedule.get_jobs(channel_name))}")
##                schedule.clear(channel_name)
##                logging.info(f"Jobs after clearing: {len(schedule.get_jobs(channel_name))}")

        #schedule.every().day.at(upload_time).do(job).tag(channel_name)

        # Convert upload_time to datetime object
        try:
            upload_time_obj = datetime.datetime.strptime(upload_time, "%H:%M")
            # Calculate processing time (2 hours before)
            process_time_obj = upload_time_obj - datetime.timedelta(hours=2)
            process_time = process_time_obj.strftime("%H:%M")
            
            logging.info(f"Scheduling {channel_name} to process at {process_time} for {upload_time} upload")
            
            for day in upload_days:
                schedule.every().day.at(process_time).do(job).tag(channel_name)
                
        except ValueError as e:
            logging.error(f"Invalid time format for {channel_name}: {e}")

    def setup_all_schedules(self):
        """Set up schedules for all channels"""
        for channel_name, config in self.schedules.items():
            self.schedule_channel(
                channel_name, 
                config["upload_time"], 
                config["upload_days"]
            )

def process_channel(channel_name, upload_time, client_id, client_secret):
    try:
        # Initialize channel manager
        channel_manager = ChannelManager()
        
        # Get access token
        access_token = get_access_token(client_id, client_secret)
        
        # Get user ID
        user_id = get_user_id(channel_name, client_id, access_token)
        
        # Get clips
        clips = get_top_clips(user_id, client_id, access_token)
        
        if not clips:
            logging.warning(f"No clips found for {channel_name}")
            return
            
        # Download clips
        output_dir = f"downloaded_clips_{channel_name}"
        video_files = download_clips(clips, output_dir)
        
        if not video_files:
            logging.warning(f"No clips were successfully downloaded for {channel_name}")
            return
            
        # Combine clips
        output_file = f"{channel_name}_top_clips.mp4"
        combine_videos_with_ffmpeg(video_files, output_file, channel_name)
        
        # Get video number
        video_number = channel_manager.increment_video_count(channel_name)
        youtube = authenticate_youtube()
        video_id = upload_to_youtube(
            youtube, 
            output_file, 
            channel_name, 
            video_number, 
            upload_time,
            clips,
            video_files
        )
        
        logging.info(f"Successfully processed {channel_name} - Video #{video_number}")
        
    except Exception as e:
        logging.error(f"Error processing {channel_name}: {str(e)}")
        raise
    finally:
        # Cleanup
        if 'output_dir' in locals() and os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        if 'output_file' in locals() and os.path.exists(output_file):
            os.remove(output_file)

def run_scheduler():
    """Main function to run the scheduler with credential validation"""
    scheduler = ChannelScheduler()
    
    def validate_youtube_credentials():
        """Validate YouTube credentials before entering automatic mode"""
        try:
            logging.info("Validating YouTube credentials...")
            youtube = authenticate_youtube()
            # Test using a simpler API call
            request = youtube.videos().list(
                part="snippet",
                maxResults=1,
                myRating="like"
            )
            request.execute()
            logging.info("YouTube credentials are valid")
            return True
        except Exception as e:
            logging.error(f"YouTube credential validation failed: {str(e)}")
            return False
    
    # Command-line interface for managing schedules
    while True:
        try:
            command = input("\nEnter command (add/remove/list/quit): ").lower()
            
            if command == "add":
                channel_name = input("Enter channel name: ")
                upload_time = input("Enter upload time (HH:MM): ")
                days_input = input("Enter upload days (comma-separated, e.g., Monday,Thursday): ")
                upload_days = [day.strip() for day in days_input.split(",")]
                scheduler.add_channel(channel_name, upload_time, upload_days)
                
            elif command == "remove":
                channel_name = input("Enter channel name to remove: ")
                scheduler.remove_channel(channel_name)
                
            elif command == "list":
                print("\nCurrent schedules:")
                if scheduler.schedules:
                    for channel, config in scheduler.schedules.items():
                        print(f"{channel}: Upload at {config['upload_time']} on {', '.join(config['upload_days'])}")
                else:
                    print("No channels currently scheduled.")
                    
            elif command == "quit":
                print("Validating YouTube credentials before entering automatic mode...")
                if not validate_youtube_credentials():
                    print("ERROR: YouTube credentials are invalid or expired.")
                    retry = input("Would you like to retry authentication? (y/n): ").lower()
                    if retry == 'y':
                        # Remove existing token to force new authentication
                        if os.path.exists("token.pickle"):
                            os.remove("token.pickle")
                        if validate_youtube_credentials():
                            print("Authentication successful!")
                            break
                        else:
                            print("Authentication failed. Please check your credentials and try again.")
                            continue
                    else:
                        print("Exiting program. Please fix YouTube credentials before running again.")
                        sys.exit(1)
                else:
                    print("YouTube credentials validated successfully.")
                    print("Entering automatic mode. Press Ctrl+C to exit.")
                    break
                
            else:
                print("Invalid command")
                
        except Exception as e:
            logging.error(f"Error in command processing: {str(e)}")
    
    # Set up all scheduled jobs
    scheduler.setup_all_schedules()
    
    # Run continuously
    logging.info("Starting scheduler in automatic mode...")
    while True:
        try:
            schedule.run_pending()
            time_module.sleep(60)
        except KeyboardInterrupt:
            logging.info("Shutting down scheduler...")
            break
        except Exception as e:
            logging.error(f"Error in scheduler: {str(e)}")
            time_module.sleep(60)

def get_cpu_temp():
    with open('/sys/class/thermal/thermal_zone0/temp', 'r') as file:
        temp = int(file.read().strip()) / 1000.0  # Convert from millidegrees to degrees Celsius
    return temp

def log_cpu_temp(log_file="cpu_temp_log.txt", interval=5):
    with open(log_file, "a") as log:
        while True:
            temp = get_cpu_temp()
            log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}: {temp}°C\n")
            log.flush()  # Ensure data is written immediately
            time.sleep(interval)  # Log every 'interval' seconds

def main():
    # Twitch API credentials
    client_id = "w4qeait6mrz9ufwnnaiz0qifv2fakg"
    client_secret = "9r34cfj51i0n816sgondtsaw8wwrdo"
    
    # Initialize channel manager
    channel_manager = ChannelManager()
    
    # Get channel name and schedule time if not already set
    channel_name = input("Enter the Twitch channel name: ")
    if not channel_manager.get_schedule_time(channel_name):
        schedule_time = input("Enter the time for videos to go live (24-hour format HH:MM): ")
        channel_manager.set_schedule_time(channel_name, schedule_time)
    
    start = time.time()
    output_dir = "downloaded_clips"
    output_file = f"{channel_name}_top_clips.mp4"  # Initialize output_file at the start
    
    try:
        # Get clips and create compilation
        print("Getting access token...")
        access_token = get_access_token(client_id, client_secret)
        
        print("Getting user ID...")
        user_id = get_user_id(channel_name, client_id, access_token)
        
        print("Getting top clips...")
        clips = get_top_clips(user_id, client_id, access_token)
        
        if not clips:
            print("No clips found for this channel in the past 7 days.")
            return
        
        # Print clips information for debugging
        print("\nClips to be downloaded:")
        for i, clip in enumerate(clips, 1):
            print(f"{i}. Title: {clip['title']}")
            print(f"   Slug: {clip['slug']}")
            print(f"   Views: {clip['view_count']}")
            
        print("\nDownloading clips...")
        video_files = download_clips(clips, output_dir)
        
        if not video_files:
            print("No clips were successfully downloaded.")
            return
            
        print("\nCombining clips into final video...")
        combine_videos_with_ffmpeg(video_files, output_file, channel_name)
        
        # Increment video count and get scheduled time
        video_number = channel_manager.increment_video_count(channel_name)
        scheduled_time = channel_manager.get_schedule_time(channel_name)
        
        # Upload to YouTube
        print("\nUploading to YouTube...")
        youtube = authenticate_youtube()
        video_id = upload_to_youtube(
            youtube, 
            output_file, 
            channel_name, 
            video_number, 
            scheduled_time,
            clips,  # Pass the clips list
            video_files  # Pass the video files list
        )
        
        print(f"\nProcess completed successfully!")
        print(f"Video #{video_number} has been uploaded and scheduled.")
        
        end = time.time()
        elapsed_time = end - start
        elapsed_minutes = int(elapsed_time // 60)
        elapsed_seconds = int(elapsed_time % 60)
        print(f"Completed in {elapsed_minutes}:{elapsed_seconds:02}.")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Clean up downloaded clips and output file
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        if os.path.exists(output_file):
            os.remove(output_file)

if __name__ == "__main__":
    # Start logging CPU temperature in a separate thread
    temp_thread = threading.Thread(target=log_cpu_temp, args=("cpu_temp_log.txt", 5), daemon=True)
    temp_thread.start()

    run_scheduler()
