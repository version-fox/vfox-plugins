#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import hashlib
import requests
from pathlib import Path
from typing import Dict, Any, Optional, Tuple


class PluginUpdater:
    def __init__(self, source_dir: str, target_dir: str):
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.tmp_zip_file = Path("tmp.zip")
        self.index_json_file = self.target_dir / "index.json"
        
        if not self.source_dir.exists():
            print(f"Error: source directory {source_dir} does not exist")
            sys.exit(1)
        
        if not self.target_dir.exists():
            self.target_dir.mkdir(parents=True, exist_ok=True)
    
    def configure_git(self) -> None:
        """Configure git user for commits"""
        subprocess.run([
            "git", "config", "--local", "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com"
        ], check=False)
        subprocess.run([
            "git", "config", "--local", "user.name",
            "github-actions[bot]"
        ], check=False)
    
    def download_manifest(self, manifest_url: str) -> Optional[Dict[str, Any]]:
        """Download manifest from URL"""
        try:
            response = requests.get(manifest_url, timeout=30)
            if response.status_code != 200:
                print(f"Failed to download manifest: {manifest_url} (HTTP {response.status_code})")
                return None
            
            manifest = response.json()
            return manifest
        except Exception as e:
            print(f"Error downloading manifest: {e}")
            return None
    
    def calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 hash of a file"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    def download_zip(self, download_url: str) -> bool:
        """Download zip file and calculate SHA256"""
        try:
            response = requests.get(download_url, timeout=60, stream=True)
            if response.status_code != 200:
                print(f"Failed to download: {download_url}")
                return False
            
            with open(self.tmp_zip_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            print(f"Error downloading zip: {e}")
            return False
    
    def check_version_changed(self, plugin_name: str, new_version: str) -> bool:
        """Check if version has changed. Returns True if changed, False if same."""
        plugin_json_file = self.target_dir / f"{plugin_name}.json"
        
        if not plugin_json_file.exists():
            return True  # New plugin
        
        try:
            with open(plugin_json_file, 'r') as f:
                current_data = json.load(f)
                current_version = current_data.get('version', '')
                
                if current_version == new_version:
                    print(f"Version unchanged: {current_version}")
                    return False
        except Exception as e:
            print(f"Error reading current version: {e}")
        
        return True
    
    def process_plugin(self, source_file: Path) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """Process a single plugin source file. Returns (version_changed, manifest_data)"""
        try:
            with open(source_file, 'r') as f:
                source_data = json.load(f)
            
            source_name = source_data.get('name')
            manifest_url = source_data.get('manifestUrl')
            
            print(f"::::[Processing] {source_name} => {manifest_url}")
            
            # Download and validate manifest
            manifest = self.download_manifest(manifest_url)
            if not manifest:
                return False, None
            
            manifest_name = manifest.get('name')
            
            # Check if name matches
            if manifest_name != source_name:
                print(f"Name mismatch: source={source_name}, manifest={manifest_name}")
                return False, None
            
            # Check if version has changed
            new_version = manifest.get('version')
            version_changed = self.check_version_changed(manifest_name, new_version)
            
            if not version_changed:
                print(f"No update needed for {manifest_name}")
                return False, manifest
            
            # Download plugin zip and calculate SHA256
            download_url = manifest.get('downloadUrl')
            print(f"::::[Downloading] {download_url} for SHA256")
            
            if self.download_zip(download_url):
                sha256 = self.calculate_sha256(self.tmp_zip_file)
                print(f"::::[SHA256] {sha256}")
                manifest['sha256'] = sha256
                self.tmp_zip_file.unlink()  # Remove temp zip
            else:
                print(f"Failed to download {download_url}")
                return False, None
            
            # Save plugin JSON
            plugin_json_file = self.target_dir / f"{manifest_name}.json"
            with open(plugin_json_file, 'w') as f:
                json.dump(manifest, f, indent=2)
            
            # Commit if version changed
            if version_changed:
                subprocess.run(["git", "add", str(plugin_json_file)], check=False)
                subprocess.run([
                    "git", "commit", "-m",
                    f"{manifest_name}: Update to version {new_version}"
                ], check=False)
            
            return True, manifest
            
        except Exception as e:
            print(f"Error processing {source_file}: {e}")
            return False, None
    
    def update_all_plugins(self) -> None:
        """Process all plugins in source directory"""
        print(f"Updating plugins: source={self.source_dir}, target={self.target_dir}")
        
        self.configure_git()
        
        index_data = []
        
        # Process each source file
        for source_file in sorted(self.source_dir.glob("*.json")):
            version_changed, manifest = self.process_plugin(source_file)
            
            if manifest:
                # Add to index
                index_entry = {
                    "name": manifest.get('name'),
                    "desc": manifest.get('description', ''),
                    "homepage": manifest.get('homepage', '')
                }
                index_data.append(index_entry)
            
            print(f"::::[End processing] {source_file.stem}\n")
        
        # Write index.json
        with open(self.index_json_file, 'w') as f:
            json.dump(index_data, f, indent=2)
        
        print(f"Index file: {self.index_json_file}")
        
        # Commit index.json if changed
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True
        )
        
        if "plugins/index.json" in result.stdout:
            subprocess.run(["git", "add", str(self.index_json_file)], check=False)
            subprocess.run([
                "git", "commit", "-m",
                "Update plugin index"
            ], check=False)
        else:
            print("No changes in index.json, skipping commit")


def main():
    if len(sys.argv) < 3:
        print("Usage: update_plugin.py <source_dir> <target_dir>")
        sys.exit(1)
    
    source_dir = sys.argv[1]
    target_dir = sys.argv[2]
    
    updater = PluginUpdater(source_dir, target_dir)
    updater.update_all_plugins()


if __name__ == "__main__":
    main()
