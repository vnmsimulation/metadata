import discord
import os
import json
import requests
import asyncio
from datetime import datetime

# Configuration
FORUM_CHANNEL_ID = 1402645649748398130
FILE_EXTENSIONS = [".vnmprofile", ".tmprofile"]
PROFILES_DIR = "profiles"
DB_DIR = "db"
PAGE_SIZE = 100
GITHUB_REPO = "vnmsimulation/metadata"  # Adjust if needed
GITHUB_RAW_BASE_URL = f"https://files.vnmsimulation.com/{PROFILES_DIR}/"

# Ensure directories exist
os.makedirs(PROFILES_DIR, exist_ok=True)
os.makedirs(DB_DIR, exist_ok=True)

class SyncClient(discord.Client):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.new_records = []
        self.existing_ids = set()
        self.manifest = {"total_records": 0, "total_pages": 0, "last_sync_time": ""}

    def load_manifest(self):
        path = os.path.join(DB_DIR, "manifest.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                self.manifest = json.load(f)
        
        # Load all existing IDs from current shards to prevent duplicates
        for i in range(1, self.manifest.get("total_pages", 0) + 1):
            shard_path = os.path.join(DB_DIR, f"page_{i}.json")
            if os.path.exists(shard_path):
                with open(shard_path, "r") as f:
                    data = json.load(f)
                    for item in data:
                        self.existing_ids.add(item["thread_id"])

    async def on_ready(self):
        print(f'Logged in as {self.user}')
        self.load_manifest()
        await self.sync_forum()
        self.save_data()
        await self.close()

    async def sync_forum(self):
        channel = self.get_channel(FORUM_CHANNEL_ID)
        if not channel:
            print(f"Error: Could not find channel {FORUM_CHANNEL_ID}")
            return

        print(f"Fetching threads from {channel.name}...")
        
        threads = []
        # Active threads
        threads.extend(channel.threads)
        # Archived threads
        async for thread in channel.archived_threads():
            threads.append(thread)

        print(f"Found {len(threads)} threads. Scanning for new {FILE_EXTENSION} files...")

        for thread in threads:
            if thread.id in self.existing_ids:
                continue

            # Scan first 5 messages
            async for message in thread.history(limit=5, oldest_first=True):
                for attachment in message.attachments:
                    if any(attachment.filename.endswith(ext) for ext in FILE_EXTENSIONS):
                        reaction_count = sum(r.count for r in message.reactions)
                        await self.process_attachment(thread, attachment, message.author.name, message.created_at, reaction_count)

    async def process_attachment(self, thread, attachment, author_name, timestamp, reaction_count):
        filename = f"{thread.id}_{attachment.filename}"
        local_path = os.path.join(PROFILES_DIR, filename)
        
        print(f"Downloading {attachment.filename} from thread '{thread.name}' by {author_name} ({reaction_count} reactions)...")
        
        try:
            response = requests.get(attachment.url)
            if response.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(response.content)
                
                # We'll store the core thread info and the file info separately for now
                file_info = {
                    "filename": filename,
                    "timestamp": timestamp.isoformat(),
                    "github_raw_url": GITHUB_RAW_BASE_URL + filename,
                    "reaction_count": reaction_count
                }
                
                # Find or create thread record
                thread_record = None
                for rec in self.new_records:
                    if rec["thread_id"] == thread.id:
                        thread_record = rec
                        break
                
                if not thread_record:
                    thread_record = {
                        "thread_id": thread.id,
                        "thread_name": thread.name,
                        "author_name": author_name,
                        "files": []
                    }
                    self.new_records.append(thread_record)
                
                thread_record["files"].append(file_info)
            else:
                print(f"Failed to download attachment: {response.status_code}")
        except Exception as e:
            print(f"Error processing attachment: {e}")

    def save_data(self):
        if not self.new_records:
            print("No new records to save.")
            return

        print(f"Adding records from {len(self.new_records)} new threads...")

        # Load all existing records
        all_threads = {}
        for i in range(1, self.manifest.get("total_pages", 0) + 1):
            shard_path = os.path.join(DB_DIR, f"page_{i}.json")
            if os.path.exists(shard_path):
                with open(shard_path, "r") as f:
                    data = json.load(f)
                    for thread in data:
                        all_threads[thread["thread_id"]] = thread
        
        # Merge new records into existing ones
        for new_thread in self.new_records:
            tid = new_thread["thread_id"]
            if tid in all_threads:
                # Merge files, avoid duplicates
                existing_filenames = {f["filename"] for f in all_threads[tid]["files"]}
                for f in new_thread["files"]:
                    if f["filename"] not in existing_filenames:
                        all_threads[tid]["files"].append(f)
            else:
                all_threads[tid] = new_thread

        # Convert back to list and sort by the LATEST file timestamp in each thread
        thread_list = list(all_threads.values())
        for thread in thread_list:
            # Sort files within thread by timestamp DESC
            thread["files"].sort(key=lambda x: x["timestamp"], reverse=True)
            # Use top file's timestamp for thread sorting
            thread["_sort_key"] = thread["files"][0]["timestamp"]

        thread_list.sort(key=lambda x: (x["_sort_key"], x["thread_id"]), reverse=True)

        # Cleanup sort key before saving
        for thread in thread_list:
            del thread["_sort_key"]

        # Re-shard
        total_records = len(thread_list)
        total_pages = (total_records + PAGE_SIZE - 1) // PAGE_SIZE

        for i in range(total_pages):
            page_num = i + 1
            start = i * PAGE_SIZE
            end = start + PAGE_SIZE
            shard_data = thread_list[start:end]
            shard_path = os.path.join(DB_DIR, f"page_{page_num}.json")
            with open(shard_path, "w") as f:
                json.dump(shard_data, f, indent=2)

        # Update manifest
        self.manifest["total_records"] = total_records
        self.manifest["total_pages"] = total_pages
        self.manifest["last_sync_time"] = datetime.utcnow().isoformat() + "Z"
        
        with open(os.path.join(DB_DIR, "manifest.json"), "w") as f:
            json.dump(self.manifest, f, indent=2)

        # Update search index
        search_index = []
        for thread in thread_list:
            search_index.append({
                "id": thread["thread_id"],
                "keywords": f"{thread['author_name']} {thread['thread_name']}".lower()
            })
        
        with open(os.path.join(DB_DIR, "search_index.json"), "w") as f:
            json.dump(search_index, f, indent=2)

        print("Sync complete.")

if __name__ == "__main__":
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        print("Error: DISCORD_BOT_TOKEN environment variable not set.")
        exit(1)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.guilds = True

    client = SyncClient(intents=intents)
    client.run(token)
