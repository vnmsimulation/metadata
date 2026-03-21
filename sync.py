import discord
import os
import json
import requests
import asyncio
from datetime import datetime

# Configuration
FORUM_CHANNEL_ID = 1402645649748398130
FILE_EXTENSION = ".vnmprofile"
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
                    if attachment.filename.endswith(FILE_EXTENSION):
                        await self.process_attachment(thread, attachment, message.author.name)

    async def process_attachment(self, thread, attachment, author_name):
        filename = f"{thread.id}_{attachment.filename}"
        local_path = os.path.join(PROFILES_DIR, filename)
        
        print(f"Downloading {attachment.filename} from thread '{thread.name}' by {author_name}...")
        
        try:
            response = requests.get(attachment.url)
            if response.status_code == 200:
                with open(local_path, "wb") as f:
                    f.write(response.content)
                
                record = {
                    "thread_id": thread.id,
                    "thread_name": thread.name,
                    "author_name": author_name,
                    "filename": filename,
                    "timestamp": thread.created_at.isoformat(),
                    "github_raw_url": GITHUB_RAW_BASE_URL + filename
                }
                self.new_records.append(record)
            else:
                print(f"Failed to download attachment: {response.status_code}")
        except Exception as e:
            print(f"Error processing attachment: {e}")

    def save_data(self):
        if not self.new_records:
            print("No new records to save.")
            return

        print(f"Adding {len(self.new_records)} new records...")

        # Load all existing records
        all_records = []
        for i in range(1, self.manifest.get("total_pages", 0) + 1):
            shard_path = os.path.join(DB_DIR, f"page_{i}.json")
            if os.path.exists(shard_path):
                with open(shard_path, "r") as f:
                    all_records.extend(json.load(f))
        
        # Merge and sort by newest first, then by thread_id to keep them grouped
        all_records.extend(self.new_records)
        # We sort by timestamp DESC, then thread_id DESC to ensure grouping
        all_records.sort(key=lambda x: (x["timestamp"], x["thread_id"]), reverse=True)

        # Re-shard
        total_records = len(all_records)
        total_pages = (total_records + PAGE_SIZE - 1) // PAGE_SIZE

        for i in range(total_pages):
            page_num = i + 1
            start = i * PAGE_SIZE
            end = start + PAGE_SIZE
            shard_data = all_records[start:end]
            shard_path = os.path.join(DB_DIR, f"page_{page_num}.json")
            with open(shard_path, "w") as f:
                json.dump(shard_data, f, indent=2)

        # Update manifest
        self.manifest["total_records"] = total_records
        self.manifest["total_pages"] = total_pages
        self.manifest["last_sync_time"] = datetime.utcnow().isoformat() + "Z"
        
        with open(os.path.join(DB_DIR, "manifest.json"), "w") as f:
            json.dump(self.manifest, f, indent=2)

        # Update search index (unique per thread_id to keep it small)
        search_index_map = {}
        for rec in all_records:
            tid = rec["thread_id"]
            if tid not in search_index_map:
                search_index_map[tid] = {
                    "id": tid,
                    "keywords": f"{rec['author_name']} {rec['thread_name']}".lower()
                }
        
        search_index = list(search_index_map.values())
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
