from flask import Flask, request, jsonify
import asyncio
import aiohttp
import urllib3
import json
import os
import time
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

API_KEY = "STAR"
API_KEY_DISPLAY = "API_KEY=STAR"

AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

REGION_CONFIG = {
    "IND": {"token_file": "token_ind.json", "url": "https://client.ind.freefiremobile.com"},
    "BR": {"token_file": "token_br.json", "url": "https://client.us.freefiremobile.com"},
    "NA": {"token_file": "token_br.json", "url": "https://client.us.freefiremobile.com"},
    "US": {"token_file": "token_br.json", "url": "https://client.us.freefiremobile.com"},
    "SAC": {"token_file": "token_br.json", "url": "https://client.us.freefiremobile.com"},
    "DEFAULT": {"token_file": "token_bd.json", "url": "https://clientbp.ggpolarbear.com"}
}

def load_tokens_live(filename):
    filepath = os.path.join(os.path.dirname(os.path.abspath(__file__)), filename)
    if not os.path.exists(filepath):
        return []
    
    for enc in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                data = json.load(f)
            return [item["token"] for item in data if isinstance(item, dict) and "token" in item]
        except: continue
    
    try:
        with open(filepath, 'rb') as f:
            raw = f.read()
        if raw.startswith(b'\xef\xbb\xbf'): raw = raw[3:]
        data = json.loads(raw.decode('utf-8', errors='replace'))
        return [item["token"] for item in data if isinstance(item, dict) and "token" in item]
    except:
        return []

def get_region_config(region):
    return REGION_CONFIG.get(region.upper(), REGION_CONFIG["DEFAULT"])

def varint_encode(value):
    result = bytearray()
    while value > 127:
        result.append((value & 0x7F) | 0x80); value >>= 7
    result.append(value & 0x7F)
    return bytes(result)

def encrypt_body(plain_hex):
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV)
    return cipher.encrypt(pad(bytes.fromhex(plain_hex.replace(" ", "")), AES.block_size))

def parse_success_hex(hex_data):
    data = bytes.fromhex(hex_data.replace(" ", ""))
    result = {"name": "N/A", "level": "N/A"}
    
    idx = 0
    while idx < len(data) - 3:
        if data[idx] == 0x1a:
            length = data[idx + 1]
            name_start = idx + 2
            name_end = name_start + length
            if name_end <= len(data):
                name_bytes = data[name_start:name_end]
                try:
                    name = name_bytes.decode('utf-8', errors='ignore')
                    if len(name) >= 2 and not all(c in '0123456789abcdef' for c in name.lower()):
                        result["name"] = name
                        for j in range(name_end, min(name_end + 20, len(data) - 1)):
                            if data[j] == 0x30 and 1 <= data[j+1] <= 100:
                                result["level"] = data[j+1]
                                break
                        return result
                except: pass
            idx = name_end
        else:
            idx += 1
    return result

async def send_one_request_async(session, semaphore, uid, token, client_url):
    async with semaphore:
        try:
            url = f"{client_url}/Follow"
            headers = {
                'Host': client_url.replace('https://', ''),
                'User-Agent': 'Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)',
                'Accept': '*/*', 'Accept-Encoding': 'gzip',
                'Authorization': f'Bearer {token}',
                'X-GA': 'v1 1', 'ReleaseVersion': 'OB54',
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Unity-Version': '2018.4.11f1'
            }
            body = encrypt_body((b'\x08' + varint_encode(uid)).hex())
            async with session.post(url, headers=headers, data=body, ssl=False, timeout=10) as resp:
                content = await resp.read()
                if resp.status == 200:
                    hex_data = content.hex()
                    if len(content) < 50:
                        return "ALREADY", None
                    return "SUCCESS", hex_data
                return "ERROR", None
        except:
            return "ERROR", None

async def process_all_requests(uid, tokens_to_use, client_url):
    # Increased concurrency for speed
    semaphore = asyncio.Semaphore(100)
    connector = aiohttp.TCPConnector(limit=200, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [send_one_request_async(session, semaphore, uid, token, client_url) for token in tokens_to_use]
        return await asyncio.gather(*tasks)

# ==================== ROUTE ====================

@app.route('/follow', methods=['GET', 'POST'])
def follow():
    t_start = time.time()
    
    api_key = request.args.get('api_key') or request.form.get('api_key')
    target_uid = request.args.get('UID') or request.form.get('UID')
    region = request.args.get('region') or request.form.get('region', 'IND')
    follower_param = request.args.get('follower') or request.form.get('follower')
    
    # Validate API key
    if not api_key or api_key != API_KEY:
        return jsonify({"status":"error","message":f"Invalid key. {API_KEY_DISPLAY}","code":401}), 401
    
    # Validate UID
    if not target_uid:
        return jsonify({"status":"error","message":"UID required","code":400}), 400
    try:
        target_uid = int(target_uid)
    except:
        return jsonify({"status":"error","message":"Invalid UID","code":400}), 400
    
    # Validate follower parameter (now required)
    if follower_param is None:
        return jsonify({"status":"error","message":"follower parameter is required (e.g., &follower=50 or &follower=all)","code":400}), 400
    
    region = region.upper()
    config = get_region_config(region)
    client_url = config["url"]
    
    all_tokens = load_tokens_live(config["token_file"])
    if not all_tokens:
        return jsonify({"status":"error","message":f"No tokens for {region}","code":500}), 500

    # Determine tokens to use based on follower parameter
    use_all = False
    if follower_param.lower() == "all":
        use_all = True
    else:
        try:
            desired = int(follower_param)
            if desired <= 0:
                return jsonify({"status":"error","message":"follower must be > 0","code":400}), 400
            tokens_to_use = all_tokens[:desired]
        except ValueError:
            return jsonify({"status":"error","message":"follower must be integer or 'all'","code":400}), 400
    
    if use_all:
        tokens_to_use = all_tokens
    
    token_count = len(tokens_to_use)
    
    print(f"\n{'='*50}")
    print(f"  UID={target_uid} | Region={region} | Tokens={token_count}/{len(all_tokens)}")
    print(f"{'='*50}")
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    results = loop.run_until_complete(process_all_requests(target_uid, tokens_to_use, client_url))
    loop.close()
    
    added = 0
    already = 0
    failed = 0
    best_name = "N/A"
    best_level = "N/A"
    
    for status, hex_data in results:
        if status == "SUCCESS":
            added += 1
            if hex_data and best_name == "N/A":
                info = parse_success_hex(hex_data)
                best_name = info["name"]
                best_level = info["level"]
        elif status == "ALREADY":
            already += 1
        else:
            failed += 1
            
    elapsed = time.time() - t_start
    print(f"  ✅{added} | ⏭️{already} | ❌{failed} | ⚡️{elapsed:.1f}s")
    print(f"{'='*50}")
    
    return jsonify({
        "status": "success" if added > 0 or already > 0 else "error",
        "code": 200,
        "data": {
            "name": best_name,
            "uid": target_uid,
            "level": best_level,
            "region": region,
            "message": f"Success (+{added}, Already: {already}, Failed: {failed})",
            "followers_added": added,
            "followers_already": already,
            "followers_failed": failed,
            "speed": f"{elapsed:.1f}s",
            "tokens_used": token_count,
            "total_tokens_available": len(all_tokens)
        }
    }), 200

if __name__ == '__main__':
    print("=" * 50)
    print("  FF Follow API v6.5 (follower required, speed optimized)")
    print("=" * 50)
    print(f"  {API_KEY_DISPLAY}")
    print("  /follow?api_key=KEY&region=IND&UID=ID&follower=50")
    print("  (use follower=all to use all tokens)")
    print("=" * 50)
    app.run(host='0.0.0.0', port=6001, debug=True, threaded=True)