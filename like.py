import json
import time
import asyncio
import httpx

# --- Settings ---
# API का URL यहाँ डालें
API_URL = "https://ff-jwt-gen-api.lovable.app/api/public/token" 
# कितनी बार दोबारा कोशिश करनी है
MAX_RETRIES = 2 
# हर दोबारा कोशिश के बीच कितना इंतज़ार करना है (सेकंड में)
RETRY_DELAY = 3 

# --- Token Generation Logic ---

async def generate_single_token(client, uid: str, password: str):
    """API से एक टोकन जेनरेट करता है."""
    try:
        url = f"{API_URL}?uid={uid}&password={password}"
        resp = await client.get(url, timeout=180)
        
        # अगर रिक्वेस्ट सफल रही तो JSON डेटा वापस भेजें
        if resp.status_code == 200:
            return resp.json()
        # अगर सफल नहीं हुई तो None भेजें
        return None
    except Exception as e:
        # किसी भी तरह की त्रुटि होने पर प्रिंट करें
        print(f"UID {uid} के लिए त्रुटि: {e}")
        return None

async def process_account_with_retry(client, account, index):
    """एक अकाउंट को दोबारा कोशिश करने वाले लॉजिक के साथ प्रोसेस करता है."""
    uid = account['uid']
    password = account['password']
    
    # MAX_RETRIES में दी गई संख्या तक कोशिश करें
    for attempt in range(MAX_RETRIES):
        token_data = await generate_single_token(client, uid, password)
        
        # अगर टोकन मिल गया, तो डेटा लौटा दें
        if token_data and "token" in token_data:
            return {
                "status": "success",
                "account": account,
                "token_data": token_data,
                "index": index
            }
        
        # अगर यह आखिरी कोशिश नहीं है, तो इंतज़ार करें और फिर से कोशिश करें
        if attempt < MAX_RETRIES - 1:
            print(f"UID #{index + 1} {uid} - फ़ेल हुआ। {RETRY_DELAY} सेकंड बाद फिर से कोशिश की जाएगी...")
            await asyncio.sleep(RETRY_DELAY)
            
    # सभी कोशिशें फ़ेल होने पर फ़ेलियर का मैसेज लौटा दें
    return {
        "status": "failed",
        "account": account,
        "index": index
    }

async def main():
    """मुख्य फ़ंक्शन जो पूरी प्रक्रिया को चलाता है."""
    input_file = "accounts.json"
    try:
        with open(input_file) as f:
            accounts = json.load(f)
    except FileNotFoundError:
        print(f"त्रुटि: '{input_file}' फ़ाइल नहीं मिली।")
        return
    except json.JSONDecodeError:
        print(f"त्रुटि: '{input_file}' एक मान्य JSON नहीं है या खाली है।")
        return

    print(f"🚀 {len(accounts)} अकाउंट्स के लिए टोकन बनाना शुरू किया जा रहा है...")
    start_time = time.time()
    
    # रीजन के हिसाब से टोकन रखने के लिए डिक्शनरी
    result = {'IND': [], 'BR': [], 'BD': []}
    failed_accounts = []

    # httpx.AsyncClient का उपयोग करके एक साथ सभी रिक्वेस्ट भेजें
    async with httpx.AsyncClient() as client:
        # सभी अकाउंट्स के लिए टास्क बनाएँ
        tasks = [process_account_with_retry(client, acc, i) for i, acc in enumerate(accounts)]
        
        # सभी टास्क पूरे होने का इंतज़ार करें
        responses = await asyncio.gather(*tasks)

        for res in responses:
            if res['status'] == 'success':
                account = res['account']
                token_data = res['token_data']
                
                # रीजन कोड के आधार पर टोकन को सही लिस्ट में डालें
                region_code = token_data.get('region', '').upper()
                if region_code == 'IND':
                    region = 'IND'
                elif region_code in {'BR', 'US', 'SAC', 'NA'}:
                    region = 'BR'
                else:
                    region = 'BD'
                
                result[region].append({
                    'uid': account['uid'],
                    'token': token_data['token']
                })
                print(f"✅ UID #{res['index'] + 1} {account['uid']} - टोकन जेनरेट हुआ ({region})")
            else:
                # जो अकाउंट फ़ेल हो गए उन्हें लिस्ट में जोड़ें
                failed_accounts.append(res['account']['uid'])
                print(f"❌ UID #{res['index'] + 1} {res['account']['uid']} - टोकन जेनरेट नहीं हो सका।")

    # परिणामी टोकन को फ़ाइलों में सेव करें
    for region, tokens in result.items():
        if tokens:
            filename = f'token_{region.lower()}_visit.json'
            with open(filename, 'w') as f:
                json.dump(tokens, f, indent=2)
            print(f"💾 {len(tokens)} टोकन {filename} में सेव किए गए।")

    # --- विस्तृत सारांश प्रिंट करें ---
    total_time = time.time() - start_time
    print("\n" + "="*40)
    print("✨ प्रोसेस पूरा हुआ! ✨")
    print(f"⏱️ कुल समय: {total_time:.2f} सेकंड")
    print(f" कुल अकाउंट्स: {len(accounts)}")
    print(f"✔️ सफल टोकन: {len(accounts) - len(failed_accounts)}")
    print(f"❌ फ़ेल हुए अकाउंट्स: {len(failed_accounts)}")
    if failed_accounts:
        print(f"   -> फ़ेल हुए UIDs: {', '.join(failed_accounts)}")
    print("="*40)


# --- स्क्रिप्ट चलाएँ ---
if __name__ == "__main__":
    # स्क्रिप्ट को चलाने के लिए `httpx` लाइब्रेरी की ज़रूरत होगी।
    # इसे `pip install httpx` कमांड से इंस्टॉल करें।
    asyncio.run(main())
