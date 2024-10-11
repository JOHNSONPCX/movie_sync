import sys
import subprocess
import socket
import threading
import time
import json
import os
import hashlib
import random
from dataclasses import dataclass
from typing import List, Dict, Optional

def ensure_pkg_resources():
    try:
        import pkg_resources
        return pkg_resources
    except ImportError:
        print("Installing required setup tools...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', 'setuptools'])
            import pkg_resources
            return pkg_resources
        except subprocess.CalledProcessError:
            print("Failed to install setuptools. Please run:")
            print(f"{sys.executable} -m pip install --upgrade setuptools")
            sys.exit(1)

def install_required_packages():
    pkg_resources = ensure_pkg_resources()
    
    required_packages = {
        'python-vlc': 'vlc'
    }
    
    installed_packages = {pkg.key for pkg in pkg_resources.working_set}
    packages_to_install = [pkg for pkg, import_name in required_packages.items() 
                          if pkg not in installed_packages]
    
    if packages_to_install:
        print("Installing required packages...")
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install'] + packages_to_install)
            print("All required packages installed successfully!")
        except subprocess.CalledProcessError:
            print("Failed to install required packages. Please install them manually:")
            for pkg in packages_to_install:
                print(f"pip install {pkg}")
            sys.exit(1)

    try:
        import vlc
        return vlc
    except ImportError:
        print("Error: VLC media player is not installed on your system.")
        print("Please install VLC media player from: https://www.videolan.org/vlc/")
        sys.exit(1)

vlc_module = install_required_packages()

@dataclass
class MediaFile:
    path: str
    name: str
    size: int
    hash: str
    index: int

class Playlist:
    def __init__(self):
        self.media_files: List[MediaFile] = []
        self.current_index: int = -1
        self._lock = threading.Lock()

    def add_file(self, media_file: MediaFile):
        with self._lock:
            self.media_files.append(media_file)

    def get_current_file(self) -> Optional[MediaFile]:
        if 0 <= self.current_index < len(self.media_files):
            return self.media_files[self.current_index]
        return None

    def set_current_index(self, index: int) -> bool:
        with self._lock:
            if 0 <= index < len(self.media_files):
                self.current_index = index
                return True
            return False

    def next_file(self) -> Optional[MediaFile]:
        with self._lock:
            if self.media_files:
                self.current_index = (self.current_index + 1) % len(self.media_files)
                return self.get_current_file()
        return None

    def previous_file(self) -> Optional[MediaFile]:
        with self._lock:
            if self.media_files:
                self.current_index = (self.current_index - 1) % len(self.media_files)
                return self.get_current_file()
        return None

class FileHandler:
    @staticmethod
    def calculate_file_hash(filepath):
        sha256_hash = hashlib.sha256()
        with open(filepath, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()

    @staticmethod
    def get_file_info(filepath):
        return {
            "name": os.path.basename(filepath),
            "size": os.path.getsize(filepath),
            "hash": FileHandler.calculate_file_hash(filepath)
        }

def find_media_files(folder_path: str) -> List[str]:
    media_extensions = [
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
        '.mp3', '.wav', '.flac', '.m4a', '.aac',
        '.webm', '.ogg'
    ]
    
    media_files = []
    try:
        for file in os.listdir(folder_path):
            if any(file.lower().endswith(ext) for ext in media_extensions):
                full_path = os.path.join(folder_path, file)
                media_files.append(full_path)
    except Exception as e:
        print(f"Error scanning folder: {e}")
    
    return sorted(media_files)

class VLCSync:
    def __init__(self, is_host=False, host_ip=None, folder_path=None):
        self.is_host = is_host
        self.host_ip = host_ip if not is_host else socket.gethostbyname(socket.gethostname())
        self.port = 5000
        self.vlc_instance = vlc_module.Instance()
        self.player = self.vlc_instance.media_player_new()
        self.folder_path = folder_path
        self.playlist = Playlist()
        self.clients: List[socket.socket] = []
        self.server_socket = None
        self.client_socket = None
        self.running = True
        self.sync_thread = None
        self.missing_files: Dict[int, MediaFile] = {}
        self.sync_interval = 3  # Sync every 3 seconds
        self.last_sync_time = 0
        self.shuffle_mode = False
        self.end_reached_event = None
        
        if self.is_host:
            self.setup_server()
        else:
            self.setup_client()
            
        if folder_path:
            self.load_playlist(folder_path)
                
        self.start_sync_thread()
        self.setup_end_reached_event()

    def setup_end_reached_event(self):
        self.end_reached_event = self.player.event_manager().event_attach(
            vlc_module.EventType.MediaPlayerEndReached, self.on_end_reached
        )

    def on_end_reached(self, event):
        if self.is_host:
            self.play_next()

    def play_next(self):
        if self.shuffle_mode:
            next_index = random.randint(0, len(self.playlist.media_files) - 1)
        else:
            current_index = self.playlist.current_index
            next_index = (current_index + 1) % len(self.playlist.media_files)
        
        self.play_file(next_index)

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        return self.shuffle_mode

    def setup_server(self):
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.bind((self.host_ip, self.port))
            self.server_socket.listen(5)
            print(f"Server started on {self.host_ip}:{self.port}")
            threading.Thread(target=self.accept_connections, daemon=True).start()
        except socket.error as e:
            print(f"Failed to start server: {e}")
            sys.exit(1)

    def setup_client(self):
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.host_ip, self.port))
            print(f"Connected to host at {self.host_ip}:{self.port}")
            threading.Thread(target=self.receive_commands, daemon=True).start()
        except socket.error as e:
            print(f"Failed to connect to host: {e}")
            sys.exit(1)

    def load_playlist(self, folder_path: str):
        media_paths = find_media_files(folder_path)
        for index, path in enumerate(media_paths):
            file_info = FileHandler.get_file_info(path)
            media_file = MediaFile(
                path=path,
                name=file_info["name"],
                size=file_info["size"],
                hash=file_info["hash"],
                index=index
            )
            self.playlist.add_file(media_file)
        
        if self.is_host:
            self.broadcast_playlist()

    def broadcast_playlist(self):
        playlist_info = [
            {
                "name": media.name,
                "size": media.size,
                "hash": media.hash,
                "index": media.index
            }
            for media in self.playlist.media_files
        ]
        self.broadcast_command({
            "type": "playlist_info",
            "playlist": playlist_info
        })

    def accept_connections(self):
        while self.running:
            try:
                self.server_socket.settimeout(1.0)
                try:
                    client_socket, address = self.server_socket.accept()
                    print(f"Client connected from {address}")
                    self.clients.append(client_socket)
                    threading.Thread(target=self.handle_client, args=(client_socket,), daemon=True).start()
                except socket.timeout:
                    continue
            except Exception as e:
                if self.running:
                    print(f"Error accepting connection: {e}")

    def handle_client(self, client_socket):
        try:
            while self.running:
                client_socket.settimeout(1.0)
                try:
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    command = json.loads(data.decode())
                    self.handle_command(command, client_socket)
                except socket.timeout:
                    continue
                except json.JSONDecodeError:
                    print(f"Failed to decode command from client")
        except:
            pass
        finally:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
            client_socket.close()
            print("Client disconnected")

    def receive_commands(self):
        while self.running:
            try:
                self.client_socket.settimeout(1.0)
                try:
                    data = self.client_socket.recv(1024)
                    if not data:
                        break
                    command = json.loads(data.decode())
                    self.handle_command(command)
                except socket.timeout:
                    continue
            except Exception as e:
                if self.running:
                    print(f"Error receiving command: {e}")
                break
        print("Disconnected from host")

    def handle_command(self, command, client_socket=None):
        cmd_type = command["type"]
        
        if cmd_type == "playlist_info":
            self.handle_playlist_info(command["playlist"])
        elif cmd_type == "play_file":
            file_index = command["index"]
            if self.verify_and_load_file(file_index):
                self.play(command.get("time"))
        elif cmd_type == "play":
            self.play(command.get("time"))
        elif cmd_type == "pause":
            self.pause()
        elif cmd_type == "seek":
            time_ms = command["time"]
            self.seek(time_ms)
        elif cmd_type == "sync":
            if not self.is_host:
                self.handle_sync(command)
        elif cmd_type == "request_sync":
            if self.is_host:
                self.send_sync_command()
        elif cmd_type == "toggle_shuffle":
            if self.is_host:
                new_state = self.toggle_shuffle()
                self.broadcast_command({"type": "shuffle_state", "enabled": new_state})
        elif cmd_type == "shuffle_state":
            if not self.is_host:
                self.shuffle_mode = command["enabled"]
        elif cmd_type == "ping":
            if self.is_host and client_socket:
                self.send_command({"type": "pong"}, client_socket)
        elif cmd_type == "request_file":
            if self.is_host:
                self.handle_file_request(command)

    def handle_playlist_info(self, playlist_info):
        self.playlist = Playlist()
        missing_files = []
        
        for file_info in playlist_info:
            local_path = self.find_matching_file(file_info)
            media_file = MediaFile(
                path=local_path if local_path else "",
                name=file_info["name"],
                size=file_info["size"],
                hash=file_info["hash"],
                index=file_info["index"]
            )
            self.playlist.add_file(media_file)
            
            if not local_path:
                missing_files.append(media_file)
                self.missing_files[media_file.index] = media_file
        
        if missing_files:
            print("\nMissing files:")
            for file in missing_files:
                print(f"  - {file.name}")
            print("\nPlease ensure you have all required files in your media folder.")

    def find_matching_file(self, file_info):
        if not self.folder_path:
            return None
        
        for file_path in find_media_files(self.folder_path):
            local_info = FileHandler.get_file_info(file_path)
            if local_info["hash"] == file_info["hash"]:
                return file_path
        return None

    def verify_and_load_file(self, file_index):
        media_file = next((mf for mf in self.playlist.media_files if mf.index == file_index), None)
        if not media_file:
            print(f"File index {file_index} not found in playlist.")
            return False
        
        if not os.path.exists(media_file.path):
            print(f"File not found locally: {media_file.name}")
            self.request_file(file_index)
            return False
        
        self.playlist.set_current_index(file_index)
        media = self.vlc_instance.media_new(media_file.path)
        self.player.set_media(media)
        return True

    def request_file(self, file_index):
        if not self.is_host:
            self.send_command({
                "type": "request_file",
                "index": file_index
            }, self.client_socket)

    def handle_file_request(self, command):
        file_index = command["index"]
        media_file = next((mf for mf in self.playlist.media_files if mf.index == file_index), None)
        if media_file and os.path.exists(media_file.path):
            print(f"Client requested file: {media_file.name}")
            print("File transfer not implemented in this version.")

    def measure_latency(self):
        if not self.is_host and self.client_socket:
            try:
                start_time = time.time()
                self.send_command({"type": "ping"}, self.client_socket)
                self.client_socket.settimeout(1.0)
                data = self.client_socket.recv(1024)
                if data and json.loads(data.decode())["type"] == "pong":
                    end_time = time.time()
                    return (end_time - start_time) * 1000
            except:
                pass
        return 0

    def play(self, time_ms=None):
        if time_ms is not None:
            self.player.set_time(time_ms)
        self.player.play()
        if self.is_host:
            time.sleep(0.1)  # Small delay to ensure playback has started
            current_time = self.player.get_time()
            self.broadcast_command({
                "type": "play",
                "time": current_time
            })

    def pause(self):
        self.player.pause()
        if self.is_host:
            self.broadcast_command({"type": "pause"})

    def seek(self, time_ms):
        self.player.set_time(time_ms)
        if self.is_host:
            self.broadcast_command({"type": "seek", "time": time_ms})

    def play_file(self, index):
        if self.verify_and_load_file(index):
            if self.is_host:
                self.player.play()
                time.sleep(0.1)  # Small delay to ensure playback has started
                current_time = self.player.get_time()
                self.broadcast_command({
                    "type": "play_file",
                    "index": index,
                    "time": current_time
                })
            else:
                self.play()

    def next_file(self):
        next_media = self.playlist.next_file()
        if next_media:
            self.play_file(next_media.index)

    def previous_file(self):
        prev_media = self.playlist.previous_file()
        if prev_media:
            self.play_file(prev_media.index)

    def send_command(self, command, client_socket):
        try:
            client_socket.send(json.dumps(command).encode())
        except:
            if client_socket in self.clients:
                self.clients.remove(client_socket)
                print("Client disconnected")

    def broadcast_command(self, command):
        for client in self.clients[:]:  # Use a slice copy to avoid modification during iteration
            self.send_command(command, client)

    def handle_sync(self, command):
        if not self.is_host:
            host_time = command["time"]
            sync_time = command["sync_time"]
            current_time = int(time.time() * 1000)  # Current time in milliseconds
            
            time_diff = current_time - sync_time
            adjusted_host_time = host_time + time_diff
            
            if self.player.is_playing():
                current_player_time = self.player.get_time()
                player_time_diff = current_player_time - adjusted_host_time
                
                if abs(player_time_diff) > 100:  # More than 100ms out of sync
                    self.player.set_time(adjusted_host_time)
            else:
                # If not playing, just set the time
                self.player.set_time(adjusted_host_time)

    def start_sync_thread(self):
        self.sync_thread = threading.Thread(target=self.sync_playback, daemon=True)
        self.sync_thread.start()

    def send_sync_command(self):
        if self.is_host and self.player.is_playing():
            current_time = self.player.get_time()
            sync_time = int(time.time() * 1000)  # Current time in milliseconds
            self.broadcast_command({
                "type": "sync",
                "time": current_time,
                "sync_time": sync_time
            })

    def sync_playback(self):
        while self.running:
            current_time = time.time()
            if current_time - self.last_sync_time >= self.sync_interval:
                self.last_sync_time = current_time
                if self.is_host:
                    self.send_sync_command()
            time.sleep(0.1)  # Sleep for a short time to reduce CPU usage

    def cleanup(self):
        self.running = False
        if self.end_reached_event:
            self.player.event_manager().event_detach(self.end_reached_event)
        if self.is_host:
            if self.server_socket:
                self.server_socket.close()
            for client in self.clients:
                try:
                    client.close()
                except:
                    pass
        else:
            if self.client_socket:
                self.client_socket.close()
        self.player.stop()

def main():
    sync = None
    try:
        print("VLC Sync - Watch together!")
        print("This program allows you to synchronize media playback across multiple computers.")
        
        folder_path = input("Enter the folder path containing your media files: ").strip().strip('"')
        if not os.path.exists(folder_path):
            print("Folder not found. Exiting...")
            return

        choice = input("Are you the host? (y/n): ").lower()
        is_host = choice == 'y'
        
        if is_host:
            host_ip = socket.gethostbyname(socket.gethostname())
            print(f"Your IP address is: {host_ip}")
            sync = VLCSync(is_host=True, folder_path=folder_path)
            
            if not sync.playlist.media_files:
                print("No media files found in the specified folder. Exiting...")
                return
            
            print("\nPlaylist:")
            for media in sync.playlist.media_files:
                print(f"{media.index + 1}. {media.name}")
            
            print("\nAvailable commands:")
            print("play <number> - Play a specific file from the playlist")
            print("next - Play the next file")
            print("prev - Play the previous file")
            print("pause - Pause/resume the current file")
            print("seek <seconds> - Seek to a specific time")
            print("sync - Force synchronization with all clients")
            print("shuffle - Toggle shuffle mode")
            print("quit - Exit the program")

            while True:
                try:
                    cmd = input("Enter command: ").lower().split()
                    if not cmd:
                        continue
                    
                    if cmd[0] == 'quit':
                        break
                    elif cmd[0] == 'play' and len(cmd) > 1:
                        try:
                            index = int(cmd[1]) - 1
                            sync.play_file(index)
                        except ValueError:
                            print("Invalid file number")
                    elif cmd[0] == 'next':
                        sync.play_next()
                    elif cmd[0] == 'prev':
                        sync.previous_file()
                    elif cmd[0] == 'pause':
                        sync.pause()
                    elif cmd[0] == 'seek' and len(cmd) > 1:
                        try:
                            seconds = float(cmd[1])
                            sync.seek(int(seconds * 1000))
                        except ValueError:
                            print("Invalid seek time")
                    elif cmd[0] == 'sync':
                        sync.send_sync_command()
                        print("Sync command sent to all clients")
                    elif cmd[0] == 'shuffle':
                        new_state = sync.toggle_shuffle()
                        print(f"Shuffle mode {'enabled' if new_state else 'disabled'}")
                    else:
                        print("Unknown command")
                except Exception as e:
                    print(f"Error executing command: {e}")
        else:
            host_ip = input("Enter the host's IP address: ")
            sync = VLCSync(is_host=False, host_ip=host_ip, folder_path=folder_path)
            print("Connected to host. Waiting for playlist information...")
            
            print("\nAvailable commands:")
            print("sync - Request synchronization from the host")
            print("quit - Exit the program")
            print("Playback is controlled by the host.")
            
            while True:
                cmd = input().lower()
                if cmd == 'quit':
                    break
                elif cmd == 'sync':
                    sync.send_command({"type": "request_sync"}, sync.client_socket)
                    print("Sync request sent to host")
    
    except KeyboardInterrupt:
        print("\nProgram interrupted by user")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        if sync:
            sync.cleanup()
        print("Program ended")

if __name__ == "__main__":
    main()