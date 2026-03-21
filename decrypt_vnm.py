import base64
import json
import os
import hashlib
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

PROFILE_TYPE_MAP = {
    0: "Unknown",
    1: "Base",
    2: "DirectDrive",
    3: "Motion",
    4: "Telemetry"
}

def derive_key(password):
    # Hash password using SHA-256 (UTF-16LE encoding for Delphi/Windows compatibility)
    pw_bytes = password.encode('utf-16le')
    h = hashlib.sha256(pw_bytes).digest()
    # CryptDeriveKey with AES-128 and SHA-256 uses the first 16 bytes of the hash
    return h[:16]

def decrypt_vnm_profile(file_path, password=None):
    if password is None:
        password = os.getenv('VNM_PROFILE_KEY')
    
    if not password:
        return {"Version": "Unknown", "ProfileType": 0, "ProfileData": {}}

    try:
        if not os.path.exists(file_path):
            print(f"Error: File not found: {file_path}")
            return None

        with open(file_path, 'r') as f:
            encrypted_b64 = f.read().strip()

        # Decode Base64
        encrypted_data = base64.b64decode(encrypted_b64)

        # AES-128-CBC with zero IV
        key = derive_key(password)
        iv = b'\x00' * 16 # Default IV for Windows CryptoAPI if not specified
        
        cipher = AES.new(key, AES.MODE_CBC, iv=iv)
        
        # Windows CryptDecrypt with Final=True uses PKCS7 padding
        decrypted_data_padded = cipher.decrypt(encrypted_data)
        
        try:
            decrypted_data = unpad(decrypted_data_padded, AES.block_size)
        except ValueError:
            # Fallback for some versions that might not use standard PKCS7 or have trailing nulls
            decrypted_data = decrypted_data_padded.rstrip(b'\x00')

        # Decode UTF-16LE (Delphi string format)
        result_str = decrypted_data.decode('utf-16le')
        
        # Parse JSON
        profile = json.loads(result_str)
        return profile

    except Exception as e:
        print(f"Error decrypting profile: {e}")
        return None

def main():
    import sys
    if len(sys.argv) < 2:
        print("Usage: python decrypt_vnm.py <path_to_vnmprofile>")
        print("Note: Ensure VNM_PROFILE_KEY environment variable is set.")
        return

    file_path = sys.argv[1]
    profile = decrypt_vnm_profile(file_path)

    if profile:
        p_type = profile.get('ProfileType', 0)
        p_type_str = PROFILE_TYPE_MAP.get(p_type, f"Unknown ({p_type})")
        
        print(f"File: {file_path}")
        print(f"Version: {profile.get('Version', 'N/A')}")
        print(f"Profile Type: {p_type_str}")
        print("-" * 20)
        # Uncomment to see the full data
        # print(json.dumps(profile.get('ProfileData', {}), indent=2))
    else:
        print("Failed to decrypt or parse the profile.")

if __name__ == "__main__":
    main()
