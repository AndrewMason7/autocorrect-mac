import logging
import sys
import time
import threading
import queue
import fcntl
import os
from logging.handlers import RotatingFileHandler
from pynput import keyboard
from AppKit import NSEvent, NSEventModifierFlagCommand, NSEventModifierFlagOption, NSEventModifierFlagControl, NSProcessInfo, NSActivityUserInitiated, NSActivityLatencyCritical

# Global reference to keep lock file handle alive
_lock_file_handle = None

def enforce_singleton():
    global _lock_file_handle
    # Primary lock path in user home, fallback to /tmp if home is read-only (e.g. Recovery Mode)
    lock_paths = [
        os.path.expanduser("~/.autocorrect.lock"),
        "/tmp/.autocorrect.lock"
    ]
    
    last_err = None
    for lock_path in lock_paths:
        try:
            # Ensure directories exist
            os.makedirs(os.path.dirname(lock_path), exist_ok=True)
            _lock_file_handle = open(lock_path, "w")
            # Try to acquire exclusive, non-blocking lock
            fcntl.flock(_lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return  # Lock acquired successfully
        except BlockingIOError:
            # Another process holds the lock - exit immediately
            sys.stderr.write("Another instance of autocorrect is already running. Exiting.\n")
            sys.exit(0)
        except Exception as e:
            # Write/permission error - try the fallback path
            last_err = e
            continue
            
    # Fallback in case both directories are write-restricted
    sys.stderr.write(f"Warning: Could not create lock file due to: {last_err}. Proceeding with caution.\n")

# Setup production-safe rotating file logging
log_handlers = [
    RotatingFileHandler(
        os.path.expanduser("~/autocorrect.log"),
        maxBytes=5 * 1024 * 1024,  # 5 MB limit per log file
        backupCount=3,             # Keep up to 3 old rotated log files
        encoding="utf-8"
    )
]
if sys.stdout and sys.stdout.isatty():
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers
)
logger = logging.getLogger("V26MacEngine")

grammar = {'i': 'I', "i'": "I'", 'im': "I'm", "i'm": "I'm", 'id': "I'd", "i'd": "I'd", 'ive': "I've", "i've": "I've", 'ill': "I'll", "i'll": "I'll", 'wed': "we'd", "we'd": "we'd", 'weree': "we're", "we'ree": "we're", "we're": "we're", 'weve': "we've", "we've": "we've", "we'll": "we'll", 'welll': "we'll", "we'lll": "we'll", 'youd': "you'd", "you'd": "you'd", 'youre': "you're", "you're": "you're", 'youve': "you've", "you've": "you've", 'youll': "you'll", "you'll": "you'll", 'hed': "he'd", "he'd": "he'd", 'hes': "he's", "he's": "he's", "he'll": "he'll", 'shed': "she'd", "she'd": "she'd", 'shes': "she's", "she's": "she's", 'shell': "she'll", "she'll": "she'll", 'itd': "it'd", "it'd": "it'd", "it's": "it's", 'itss': "it's", "it'ss": "it's", 'itll': "it'll", "it'll": "it'll", 'theyd': "they'd", "they'd": "they'd", 'theyre': "they're", "they're": "they're", 'theyve': "they've", "they've": "they've", 'theyll': "they'll", "they'll": "they'll", 'thats': "that's", "that's": "that's", 'thatd': "that'd", "that'd": "that'd", 'thatll': "that'll", "that'll": "that'll", 'theres': "there's", "there's": "there's", 'thered': "there'd", "there'd": "there'd", 'therell': "there'll", "there'll": "there'll", 'heres': "here's", "here's": "here's", 'whats': "what's", "what's": "what's", 'whatd': "what'd", "what'd": "what'd", 'whatll': "what'll", "what'll": "what'll", 'whatve': "what've", "what've": "what've", 'wheres': "where's", "where's": "where's", 'whered': "where'd", "where'd": "where'd", 'wherell': "where'll", "where'll": "where'll", 'whereve': "where've", "where've": "where've", 'whens': "when's", "when's": "when's", 'whend': "when'd", "when'd": "when'd", 'whenve': "when've", "when've": "when've", 'whys': "why's", "why's": "why's", 'hows': "how's", "how's": "how's", 'howd': "how'd", "how'd": "how'd", 'howve': "how've", "how've": "how've", 'whos': "who's", "who's": "who's", 'whod': "who'd", "who'd": "who'd", 'wholl': "who'll", "who'll": "who'll", 'whove': "who've", "who've": "who've", 'shouldve': "should've", "should've": "should've", 'couldve': "could've", "could've": "could've", 'wouldve': "would've", "would've": "would've", 'mightve': "might've", "might've": "might've", 'mustve': "must've", "must've": "must've", 'cant': "can't", "can't": "can't", 'dont': "don't", "don't": "don't", 'wont': "won't", "won't": "won't", 'didnt': "didn't", 'isnt': "isn't", "isn't": "isn't", 'arent': "aren't", "aren't": "aren't", 'wasnt': "wasn't", "wasn't": "wasn't", 'werent': "weren't", "weren't": "weren't", 'hasnt': "hasn't", 'havent': "haven't", "haven't": "haven't", 'hadnt': "hadn't", "hadn't": "hadn't", 'doesnt': "doesn't", 'wouldnt': "wouldn't", "wouldn't": "wouldn't", 'couldnt': "couldn't", "couldn't": "couldn't", 'shouldnt': "shouldn't", "shouldn't": "shouldn't", 'mustnt': "mustn't", "mustn't": "mustn't", 'neednt': "needn't", "needn't": "needn't", 'shant': "shan't", "shan't": "shan't", 'darent': "daren't", 'aint': "ain't", "ain't": "ain't", 'lets': "let's", "let's": "let's", 'everybodys': "everybody's", "everybody's": "everybody's", 'everyones': "everyone's", "everyone's": "everyone's", 'somebodys': "somebody's", "somebody's": "somebody's", 'someones': "someone's", "someone's": "someone's", 'nobodys': "nobody's", "nobody's": "nobody's", 'anybodys': "anybody's", "anybody's": "anybody's", 'anyones': "anyone's", "anyone's": "anyone's", 'nothings': "nothing's", "nothing's": "nothing's", 'somethings': "something's", "something's": "something's", 'anythings': "anything's", "anything's": "anything's", 'everythings': "everything's", "everything's": "everything's"}
shortcuts = {'adam': 'Adam', 'alexander': 'Alexander', 'ali': 'Ali', 'andrew': 'Andrew', 'ben': 'Ben', 'benjamin': 'Benjamin', 'bob': 'Bob', 'charles': 'Charles', 'chris': 'Chris', 'damon': 'Damon', 'dan': 'Dan', 'daniel': 'Daniel', 'david': 'David', 'dylan': 'Dylan', 'elijah': 'Elijah', 'ethan': 'Ethan', 'garfield': 'Garfield', 'george': 'George', 'graham': 'Graham', 'harry': 'Harry', 'henry': 'Henry', 'isaac': 'Isaac', 'jack': 'Jack', 'jake': 'Jake', 'james': 'James', 'jann': 'Jann', 'joe': 'Joe', 'john': 'John', 'josh': 'Josh', 'joshua': 'Joshua', 'levi': 'Levi', 'lewis': 'Lewis', 'liam': 'Liam', 'logan': 'Logan', 'louis': 'Louis', 'lucas': 'Lucas', 'luke': 'Luke', 'mansell': 'Mansell', 'mansour': 'Mansour', 'marco': 'Marco', 'mark': 'Mark', 'mason': 'Mason', 'mateo': 'Mateo', 'matt': 'Matt', 'matthew': 'Matthew', 'matty': 'Matty', 'michael': 'Michael', 'mike': 'Mike', 'mohammed': 'Mohammed', 'neil': 'Neil', 'nick': 'Nick', 'noah': 'Noah', 'omar': 'Omar', 'owen': 'Owen', 'paul': 'Paul', 'peter': 'Peter', 'ryan': 'Ryan', 'sebastian': 'Sebastian', 'simon': 'Simon', 'shaun': 'Shaun', 'steve': 'Steve', 'tim': 'Tim', 'tom': 'Tom', 'victor': 'Victor', 'william': 'William', 'ايسل': 'آيسل', 'aisel': 'Aisel', 'amy': 'Amy', 'anita': 'Anita', 'anna': 'Anna', 'ava': 'Ava', 'beth': 'Beth', 'chloe': 'Chloe', 'ella': 'Ella', 'emma': 'Emma', 'gianna': 'Gianna', 'hazel': 'Hazel', 'kirsty': 'Kirsty', 'layla': 'Layla', 'lily': 'Lily', 'linda': 'Linda', 'lisa': 'Lisa', 'lucy': 'Lucy', 'luna': 'Luna', 'mary': 'Mary', 'mona': 'Mona', 'olivia': 'Olivia', 'sandra': 'Sandra', 'sofia': 'Sofia', 'sophia': 'Sophia', 'alex': 'Alex', 'harper': 'Harper', 'rei': 'Rei', 'robin': 'Robin', 'sage': 'Sage', 'sam': 'Sam', 'god': 'God', 'jesus': 'Jesus', 'christ': 'Christ', 'holy spirit': 'Holy Spirit', 'bible': 'Bible', 'buddhism': 'Buddhism', 'christianity': 'Christianity', 'christmas': 'Christmas', 'church': 'Church', 'easter': 'Easter', 'hinduism': 'Hinduism', 'islam': 'Islam', 'judaism': 'Judaism', 'jew': 'Jew', 'lgbt': 'LGBT', 'lgbtq': 'LGBTQ+', 'muslim': 'Muslim', 'prophet': 'Prophet', 'quran': 'Quran', 'saint': 'Saint', 'torah': 'Torah', 'adidas': 'Adidas', 'chanel': 'Chanel', 'dior': 'Dior', 'gucci': 'Gucci', 'hermes': 'Hermes', 'louis vuitton': 'Louis Vuitton', 'nike': 'Nike', 'prada': 'Prada', 'rolex': 'Rolex', 'tiffany': 'Tiffany', 'versace': 'Versace', 'donatella versace': 'Donatella Versace', 'zara': 'Zara', 'audi': 'Audi', 'bmw': 'BMW', 'ferrari': 'Ferrari', 'ford': 'Ford', 'honda': 'Honda', 'hyundai': 'Hyundai', 'jeep': 'Jeep', 'kia': 'Kia', 'lamborghini': 'Lamborghini', 'lexus': 'Lexus', 'mazda': 'Mazda', 'mercedes': 'Mercedes', 'nissan': 'Nissan', 'toyota': 'Toyota', 'airdrop': 'AirDrop', 'airplay': 'AirPlay', 'airpods': 'AirPods', 'airtag': 'AirTag', 'apple intelligence': 'Apple Intelligence', 'apple tv': 'Apple TV', 'apple watch': 'Apple Watch', 'apple music': 'Apple Music', 'carplay': 'CarPlay', 'face id': 'Face ID', 'facetime': 'FaceTime', 'homekit': 'HomeKit', 'homepod': 'HomePod', 'icloud': 'iCloud', 'imac': 'iMac', 'ios': 'iOS', 'ipad': 'iPad', 'ipados': 'iPadOS', 'iphone': 'iPhone', 'iphone15': 'iPhone 15 Pro Max', 'mac': 'Mac', 'macbook': 'MacBook', 'Macbook air': 'MacBook Air', 'Macbook pro': 'MacBook Pro', 'Macbook neo': 'MacBook Neo', 'macos': 'macOS', 'magsafe': 'MagSafe', 'siri': 'Siri', 'tvos': 'tvOS', 'ultra': 'Ultra', 'vision pro': 'Vision Pro', 'watchos': 'watchOS', 'adobe': 'Adobe', 'airbnb': 'Airbnb', 'amazon': 'Amazon', 'amd': 'AMD', 'asus': 'Asus', 'dell': 'Dell', 'fivesheep': 'FiveSheep', 'google': 'Google', 'hp': 'HP', 'ibm': 'IBM', 'intel': 'Intel', 'lenovo': 'Lenovo', 'lg': 'LG', 'meta': 'Meta', 'microsoft': 'Microsoft', 'motorola': 'Motorola', 'netflix': 'Netflix', 'nintendo': 'Nintendo', 'nvidia': 'NVIDIA', 'oneplus': 'OnePlus', 'oracle': 'Oracle', 'paypal': 'PayPal', 'playstation': 'PlayStation', 'samsung': 'Samsung', 'shopify': 'Shopify', 'sony': 'Sony', 'spacex': 'SpaceX', 'spotify': 'Spotify', 'starlink': 'Starlink', 'stripe': 'Stripe', 'tesla': 'Tesla', 'twitch': 'Twitch', 'uber': 'Uber', 'uber eats': 'Uber Eats', 'xai': 'xAI', 'xbox': 'Xbox', 'ai': 'AI', 'bard': 'Bard', 'chatgpt': 'ChatGPT', 'claude': 'Claude', 'codex': 'Codex', 'opus': 'Opus', 'openclaw': 'OpenClaw', 'sonnet': 'Sonnet', 'copilot': 'Copilot', 'dall-e': 'DALL-E', 'deepseek': 'DeepSeek', 'grok': 'Grok', 'kimi': 'Kimi', 'hugging face': 'Hugging Face', 'llm': 'LLM', 'midjourney': 'Midjourney', 'mk': 'Mister Keyboard', 'openai': 'OpenAI', 'perplexity': 'Perplexity', 'perp': 'Perplexity', 'sora': 'Sora', 'stable diffusion': 'Stable Diffusion', 'esign': 'Esign', 'ksign': 'Ksign', 'plumbsign': 'Plumbsign', 'moshi': 'Moshi', 'android': 'Android', 'bluetooth': 'Bluetooth', 'chromebook': 'Chromebook', 'cpu': 'CPU', 'gpu': 'GPU', 'hdmi': 'HDMI', 'led': 'LED', 'linux': 'Linux', 'nfc': 'NFC', 'oled': 'OLED', 'pixel': 'Pixel', 'ram': 'RAM', 'rom': 'ROM', 'usb': 'USB', 'usb c': 'USB-C', 'usb-c': 'USB-C', 'vr': 'VR', 'wifi': 'Wi-Fi', 'youtube': 'YouTube', 'linkedin': 'LinkedIn', 'github': 'GitHub', 'tiktok': 'TikTok', 'whatsapp': 'WhatsApp', 'snapchat': 'Snapchat', 'facebook': 'Facebook', 'telegram': 'Telegram', 'twitter': 'Twitter', 'twt': 'Twitter', 'ime': 'iMe', 'instagram': 'Instagram', 'discord': 'Discord', 'reddit': 'Reddit', '2fa': '2FA', '4g': '4G', '5g': '5G', 'antigravity': 'Antigravity', 'api': 'API', 'apis': 'APIs', 'aws': 'AWS', 'azure': 'Azure', 'bash': 'Bash', 'bios': 'BIOS', 'cli': 'CLI', 'cmd': 'CMD', 'cortana': 'Cortana', 'cpp': 'C++', 'css': 'CSS', 'debian': 'Debian', 'dns': 'DNS', 'dev': 'developer', 'devs': 'developers', 'distro': 'Distro', 'docker': 'Docker', 'dos': 'DOS', 'excel': 'Excel', 'fedora': 'Fedora', 'gcp': 'GCP', 'git': 'Git', 'gnome': 'GNOME', 'gui': 'GUI', 'html': 'HTML', 'ide': 'IDE', 'idm': 'IDM', 'ip': 'IP', 'java': 'Java', 'javascript': 'JavaScript', 'json': 'JSON', 'kde': 'KDE', 'kernel': 'Kernel', 'lte': 'LTE', 'nextjs': 'Next.js', 'NPM': 'npm', 'oauth': 'OAuth', 'outlook': 'Outlook', 'powerpoint': 'PowerPoint', 'powershell': 'PowerShell', 'python': 'Python', 'repo-': 'Repository', 'saas': 'SaaS', 'sdk': 'SDK', 'sql': 'SQL', 'ssh': 'SSH', 'ssl': 'SSL', 'typescript': 'TypeScript', 'ubuntu': 'Ubuntu', 'ui': 'UI', 'unix': 'Unix', 'url': 'URL', 'ux': 'UX', 'vpn': 'VPN', 'wsl': 'WSL', 'xcode': 'Xcode', 'aries': 'Aries', 'taurus': 'Taurus', 'gemini': 'Gemini', 'cancer': 'Cancer', 'leo': 'Leo', 'virgo': 'Virgo', 'libra': 'Libra', 'scorpio': 'Scorpio', 'sagittarius': 'Sagittarius', 'capricorn': 'Capricorn', 'aquarius': 'Aquarius', 'pisces': 'Pisces', 'mercury': 'Mercury', 'venus': 'Venus', 'mars': 'Mars', 'jupiter': 'Jupiter', 'saturn': 'Saturn', 'uranus': 'Uranus', 'neptune': 'Neptune', 'pluto': 'Pluto', 'chiron': 'Chiron', 'lilith': 'Lilith', 'ascendant': 'Ascendant', 'retrograde': 'Retrograde', 'crystal': 'Crystal', 'quartz': 'Quartz', 'agate': 'Agate', 'amazonite': 'Amazonite', 'amethyst': 'Amethyst', 'angelite': 'Angelite', 'apatite': 'Apatite', 'aquamarine': 'Aquamarine', 'aventurine': 'Aventurine', 'bloodstone': 'Bloodstone', 'citrine': 'Citrine', 'clear quartz': 'Clear Quartz', 'fluorite': 'Fluorite', 'garnet': 'Garnet', 'hematite': 'Hematite', 'howlite': 'Howlite', 'jade': 'Jade', 'labradorite': 'Labradorite', 'lapis': 'Lapis', 'lapis lazuli': 'Lapis Lazuli', 'moonstone': 'Moonstone', 'obsidian': 'Obsidian', 'onyx': 'Onyx', 'opal': 'Opal', 'opalite': 'Opalite', 'peridot': 'Peridot', 'pyrite': 'Pyrite', 'rose quartz': 'Rose Quartz', 'selenite': 'Selenite', 'sodalite': 'Sodalite', 'sunstone': 'Sunstone', "tiger's eye": "Tiger's Eye", 'tourmaline': 'Tourmaline', 'turquoise': 'Turquoise', 'chakra': 'Chakra', 'root chakra': 'Root Chakra', 'sacral chakra': 'Sacral Chakra', 'solar plexus chakra': 'Solar Plexus Chakra', 'solar chakra': 'Solar Plexus Chakra', 'heart chakra': 'Heart Chakra', 'throat chakra': 'Throat Chakra', 'third eye chakra': 'Third Eye Chakra', 'third eye': 'Third Eye', 'crown chakra': 'Crown Chakra', 'muladhara': 'Muladhara', 'svadhishthana': 'Svadhishthana', 'manipura': 'Manipura', 'anahata': 'Anahata', 'vishuddha': 'Vishuddha', 'ajna': 'Ajna', 'sahasrara': 'Sahasrara', 'afrikaans': 'Afrikaans', 'arabic': 'Arabic', 'chinese': 'Chinese', 'danish': 'Danish', 'dutch': 'Dutch', 'english': 'English', 'filipino': 'Filipino', 'finnish': 'Finnish', 'french': 'French', 'german': 'German', 'greek': 'Greek', 'hebrew': 'Hebrew', 'hindi': 'Hindi', 'indonesian': 'Indonesian', 'italian': 'Italian', 'japanese': 'Japanese', 'korean': 'Korean', 'malay': 'Malay', 'norwegian': 'Norwegian', 'persian': 'Persian', 'portuguese': 'Portuguese', 'russian': 'Russian', 'spanish': 'Spanish', 'swedish': 'Swedish', 'tagalog': 'Tagalog', 'thai': 'Thai', 'turkish': 'Turkish', 'ukrainian': 'Ukrainian', 'urdu': 'Urdu', 'vietnamese': 'Vietnamese', 'africa': 'Africa', 'antarctica': 'Antarctica', 'asia': 'Asia', 'australia': 'Australia', 'europe': 'Europe', 'north america': 'North America', 'south america': 'South America', 'america': 'America', 'argentina': 'Argentina', 'austria': 'Austria', 'bahrain': 'Bahrain', 'belgium': 'Belgium', 'brazil': 'Brazil', 'britain': 'Britain', 'canada': 'Canada', 'china': 'China', 'colombia': 'Colombia', 'denmark': 'Denmark', 'egypt': 'Egypt', 'england': 'England', 'finland': 'Finland', 'france': 'France', 'germany': 'Germany', 'great britain': 'Great Britain', 'greece': 'Greece', 'india': 'India', 'indonesia': 'Indonesia', 'iran': 'Iran', 'iraq': 'Iraq', 'ireland': 'Ireland', 'italy': 'Italy', 'japan': 'Japan', 'jordan': 'Jordan', 'korea': 'Korea', 'ksa': 'Saudi Arabia', 'kuwait': 'Kuwait', 'lebanon': 'Lebanon', 'malaysia': 'Malaysia', 'mexico': 'Mexico', 'morocco': 'Morocco', 'netherlands': 'Netherlands', 'new zealand': 'New Zealand', 'nigeria': 'Nigeria', 'northern ireland': 'Northern Ireland', 'norway': 'Norway', 'oman': 'Oman', 'pakistan': 'Pakistan', 'palestine': 'Palestine', 'peru': 'Peru', 'philippines': 'Philippines', 'poland': 'Poland', 'portugal': 'Portuguese', 'qatar': 'Qatar', 'russia': 'Russia', 'saudi arabia': 'Saudi Arabia', 'scotland': 'Scotland', 'singapore': 'Singapore', 'south africa': 'South Africa', 'spain': 'Spain', 'sweden': 'Swedish', 'switzerland': 'Switzerland', 'thailand': 'Thailand', 'turkey': 'Turkey', 'uae': 'UAE', 'UK-': 'United Kingdom', 'ukraine': 'Ukraine', 'united kingdom': 'United Kingdom', 'united states': 'United States', 'USA-': 'United States', 'vietnam': 'Vietnam', 'wales': 'Wales', 'barcelona': 'Barcelona', 'beijing': 'Beijing', 'berlin': 'Berlin', 'cairo': 'Cairo', 'dubai': 'Dubai', 'hong kong': 'Hong Kong', 'london': 'London', 'madrid': 'Madrid', 'moscow': 'Moscow', 'new york': 'New York', 'ny': 'New York', 'NY': 'New York', 'nyc': 'NYC', 'paris': 'Paris', 'rome': 'Rome', 'seoul': 'Seoul', 'sydney': 'Sydney', 'tokyo': 'Tokyo', 'toronto': 'Toronto', 'abu dhabi': 'Abu Dhabi', 'alhasa': 'Alhasa', 'dammam': 'Dammam', 'irbid': 'Irbid', 'jeddah': 'Jeddah', 'mecca': 'Mecca', 'medina': 'Medina', 'riyadh': 'Riyadh', 'sharjah': 'Sharjah', 'cheshire': 'Cheshire', 'greater manchester': 'Greater Manchester', 'kent': 'Kent', 'lancashire': 'Lancashire', 'merseyside': 'Merseyside', 'yorkshire': 'Yorkshire', 'ashton': 'Ashton', 'ashtonin': 'Ashton-in-Makerfield', 'birmingham': 'Birmingham', 'blackburn': 'Blackburn', 'blackpool': 'Blackpool', 'bolton': 'Bolton', 'bournemouth': 'Bournemouth', 'bradford': 'Bradford', 'brighton': 'Brighton', 'bristol': 'Bristol', 'burnley': 'Burnley', 'cambridge': 'Cambridge', 'cardiff': 'Cardiff', 'chester': 'Chester', 'edinburgh': 'Edinburgh', 'glasgow': 'Glasgow', 'leeds': 'Leeds', 'liverpool': 'Liverpool', 'manchester': 'Manchester', 'newcastle': 'Newcastle', 'oxford': 'Oxford', 'preston': 'Preston', 'rochdale': 'Rochdale', 'salford': 'Salford', 'salisbury': 'Salisbury', 'sheffield': 'Sheffield', 'southport': 'Southport', 'st helens': 'St Helens', 'stockport': 'Stockport', 'warrington': 'Warrington', 'wigan': 'Wigan', 'york': 'York', 'monday': 'Monday', 'tuesday': 'Tuesday', 'wednesday': 'Wednesday', 'thursday': 'Thursday', 'friday': 'Friday', 'saturday': 'Saturday', 'sunday': 'Sunday', 'mon': 'Mon', 'tue': 'Tue', 'thu': 'Thu', 'fri': 'Fri', 'january': 'January', 'february': 'February', 'march': 'March', 'april': 'April', 'june': 'June', 'july': 'July', 'august': 'August', 'september': 'September', 'october': 'October', 'november': 'November', 'december': 'December', 'jan': 'Jan', 'feb': 'Feb', 'mar': 'Mar', 'apr': 'Apr', 'may': 'May', 'jun': 'Jun', 'jul': 'Jul', 'aug': 'Aug', 'sep': 'Sep', 'oct': 'Oct', 'nov': 'Nov', 'dec': 'Dec', 'ramadan': 'Ramadan', 'eid': 'Eid', 'hanukkah': 'Hanukkah', 'halloween': 'Halloween', 'thanksgiving': 'Thanksgiving', "new year's": "New Year's", "valentine's day": "Valentine's Day", 'valentines day': "Valentine's Day", 'dob': 'DOB', 'cv': 'CV', 'atm': 'ATM', 'usd': 'USD', 'eur': 'EUR', 'gbp': 'GBP', 'ceo': 'CEO', 'cfo': 'CFO', 'coo': 'COO', 'cmo': 'CMO', 'cto': 'CTO', 'cio': 'CIO', 'cdo': 'CDO', 'fbi': 'FBI', 'cia': 'CIA', 'vip': 'VIP', 'sos': 'SOS', 'ufo': 'UFO', 'uap': 'UAP', 'qol': 'QoL', 'uni': 'university', 'omw': 'On my way!', 'adhd': 'ADHD', 'aids': 'AIDS', 'cpr': 'CPR', 'dna': 'DNA', 'ecg': 'ECG', 'ekg': 'EKG', 'er': 'ER', 'hiv': 'HIV', 'ibs': 'IBS', 'mri': 'MRI', 'nhs': 'NHS', 'ocd': 'OCD', 'ptsd': 'PTSD', "alzheimer's": "Alzheimer's", 'alzheimers': "Alzheimer's", "parkinson's": "Parkinson's", 'parkinsons': "Parkinson's", 'down syndrome': 'Down syndrome', 'afk': 'AFK', 'dlc': 'DLC', 'fps': 'FPS', 'npc': 'NPC', 'rpg': 'RPG', 'pvp': 'PvP', 'pve': 'PvE', 'xp-': 'XP', 'ariana': 'Ariana', 'grande': 'Grande', 'billie': 'Billie', 'eilish': 'Eilish', 'taylor': 'Taylor', 'swift': 'Swift', 'selena': 'Selena', 'gomez': 'Gomez', 'justin': 'Justin', 'bieber': 'Bieber', 'dua': 'Dua', 'lipa': 'Lipa', 'ed': 'Ed', 'sheeran': 'Sheeran', 'styles': 'Styles', 'miley': 'Miley', 'cyrus': 'Cyrus', 'demi': 'Demi', 'lovato': 'Lovato', 'camila': 'Camila', 'cabello': 'Cabello', 'shawn': 'Shawn', 'mendes': 'Mendes', 'katy': 'Katy', 'perry': 'Perry', 'malone': 'Malone', 'travis': 'Travis', 'scott': 'Scott', 'elon': 'Elon', 'musk': 'Musk', 'zuckerberg': 'Zuckerberg', 'kanye': 'Kanye', 'kim': 'Kim', 'khloe': 'Khloé', 'kourtney': 'Kourtney', 'kardashian': 'Kardashian', 'kendall': 'Kendall', 'kylie': 'Kylie', 'jenner': 'Jenner', 'lady gaga': 'Lady Gaga', 'lana': 'Lana', 'del rey': 'Del Rey', 'rodrigo': 'Rodrigo', 'gigi': 'Gigi', 'bella': 'Bella', 'hadid': 'Hadid', 'holland': 'Holland', 'cristiano': 'Cristiano', 'ronaldo': 'Ronaldo', 'zayn': 'Zayn', 'malik': 'Malik', 'adele': 'Adele', 'beyonce': 'Beyoncé', 'rihanna': 'Rihanna', 'shakira': 'Shakira', 'drake': 'Drake', 'zendaya': 'Zendaya', 'doja': 'Doja', 'halsey': 'Halsey', 'sia': 'Sia', 'cardi': 'Cardi', 'bad bunny': 'Bad Bunny', 'rudberg': 'Rudberg', 'gracie': 'Gracie', 'abrams': 'Abrams', 'archuleta': 'Archuleta', 'kate': 'Kate', 'bush': 'Bush', 'stevie': 'Stevie', 'nicks': 'Nicks', 'bassett': 'Bassett', 'leclerc': 'Leclerc', 'trevor': 'Trevor', 'haifa': 'Haifa', 'wehbe': 'Wehbe', 'twenty one pilots': 'Twenty One Pilots', 'niall': 'Niall', 'horan': 'Horan', 'troye': 'Troye', 'sivan': 'Sivan', 'charlie': 'Charlie', 'puth': 'Puth', 'qveen': 'Qveen', 'herby': 'Herby', 'sabrina': 'Sabrina', 'carpenter': 'Carpenter', 'hayley': 'Hayley', 'williams': 'Williams', 'paramore': 'Paramore', 'sasha': 'Sasha', 'sloan': 'Sloan', 'melanie': 'Melanie', 'martinez': 'Martinez', 'apollo': 'Apollo', 'rina': 'Rina', 'sawayama': 'Sawayama', 'tomlinson': 'Tomlinson', 'conan': 'Conan', 'gray': 'Gray', 'nicki': 'Nicki', 'minaj': 'Minaj', 'gcse': 'GCSE', 'gcses': 'GCSEs', 'mse': 'make se'}

CORRECTIONS = {**grammar, **shortcuts}
_SENTENCE_BREAK_TRIGGERS = frozenset(('.', '!', '?', '\n'))
class V26MacEngine:
    def __init__(self, corrections: dict[str, str]):
        self.corrections = corrections
        self.buffer = ""
        self.prev_words = []
        self.history = []
        self.is_sentence_start = True
        self.is_synthesizing = False
        self.synthesized_queue = []
        self.lock = threading.Lock()
        self.task_queue = queue.Queue()
        self.controller = keyboard.Controller()
        # Start simulation worker thread
        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()


    def _worker_loop(self):
        while True:
            try:
                task = self.task_queue.get()
                if task is None:
                    break
                
                chars_to_delete, corr, trigger, original = task

                logger.info("[DETECTED] Word Match: '%s' -> '%s' (Trigger: '%s', Length: %d)", original, corr, trigger.replace('\n', '\\n').replace('\t', '\\t'), len(original))
                logger.info("[SIMULATION] Entering simulation state.")
                self.is_synthesizing = True
                
                # Build the expected queue of events to ignore
                expected_events = ['backspace'] * chars_to_delete + list(corr + trigger)
                with self.lock:
                    self.synthesized_queue = expected_events

                # Wait 15ms to let the OS process the user's physical trigger keypress first
                time.sleep(0.015)

                # Perform the erasure
                logger.info("[SIMULATION] Erasing %d characters (backspaces)", chars_to_delete)
                aborted = False
                for i in range(chars_to_delete):
                    # Check for active modifiers to prevent executing dangerous system shortcuts
                    flags = NSEvent.modifierFlags()
                    if flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl):
                        logger.warning("[SIMULATION] Aborting erasure: active modifier flags detected.")
                        aborted = True
                        break
                    self.controller.tap(keyboard.Key.backspace)
                    time.sleep(0.01)

                if aborted:
                    continue

                # Post-erasure pause (10ms)
                time.sleep(0.01)
                
                # Type the correction character-by-character while monitoring modifiers
                logger.info("[SIMULATION] Typing replacement: '%s'", (corr + trigger).replace('\n', '\\n').replace('\t', '\\t'))
                for char in (corr + trigger):
                    flags = NSEvent.modifierFlags()
                    if flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl):
                        logger.warning("[SIMULATION] Aborting typing: active modifier flags detected.")
                        aborted = True
                        break
                    self.controller.type(char)
                    time.sleep(0.005)

                if aborted:
                    continue
                
                # Post-simulation cooldown (20ms)
                time.sleep(0.02)
                logger.info("[SUCCESS] Correction applied successfully.")
            except Exception as err:
                logger.error("[ERROR] Exception in simulation worker thread: %s", err)
            finally:
                self.is_synthesizing = False
                with self.lock:
                    self.synthesized_queue.clear()
                self.task_queue.task_done()

    def _check_sentence_start_before_buffer(self) -> bool:
        # Buffer characters + trigger character are at the end of history
        offset = len(self.buffer) + 1
        history_len = len(self.history)
        for i in range(history_len - 1 - offset, -1, -1):
            c = self.history[i]
            if c not in (' ', '\t'):
                return c in ('.', '!', '?', '\n')
        return True

    def _capitalize_first_alpha(self, s: str) -> str:
        for i, c in enumerate(s):
            if c.isalnum():
                if c.isalpha():
                    if c.islower():
                        return s[:i] + c.upper() + s[i+1:]
                    return s
                else:
                    return s
        return s

    def handle_char(self, char: str):
        self.history.append(char)
        if len(self.history) > 1000:
            self.history = self.history[-500:]

        if char in (' ', '.', '!', '?', ',', '\n', '\t'):
            self._handle_trigger(char)
        else:
            self.buffer += char

    def handle_backspace(self):
        if self.history:
            self.history.pop()

        if self.buffer:
            self.buffer = self.buffer[:-1]
        else:
            self.prev_words.clear()

    def reset(self):
        self.buffer = ""
        self.prev_words.clear()
        self.history.clear()

    def _preserve_case(self, original: str, replacement: str) -> str:
        if not original or not replacement:
            return replacement
        if original.isupper():
            return replacement.upper()
        if original[0].isupper():
            return replacement[0].upper() + replacement[1:]
        return replacement


    def _get_key_char(self, key) -> str:
        if hasattr(key, 'char') and key.char:
            return key.char
        if key == keyboard.Key.space:
            return ' '
        if key == keyboard.Key.enter:
            return '\n'
        if key == keyboard.Key.tab:
            return '\t'
        if key == keyboard.Key.backspace:
            return 'backspace'
        return None

    def _handle_trigger(self, trigger: str):
        word = self.buffer.lower()
        is_sentence_start = self._check_sentence_start_before_buffer()
        preserve_sentence_start = (trigger == ' ' and not word and is_sentence_start)
        corr = None
        chars_to_delete = len(self.buffer) + 1  # +1 for trigger char typed by OS

        if trigger == ' ':
            # 3-word check
            if len(self.prev_words) >= 2:
                phrase3 = f"{self.prev_words[-2][0]} {self.prev_words[-1][0]} {word}"
                if phrase3 in self.corrections:
                    corr = self.corrections[phrase3]
                    chars_to_delete = (
                        len(self.prev_words[-2][1]) + 1 +
                        len(self.prev_words[-1][1]) + 1 +
                        len(self.buffer) + 1
                    )
                    self.prev_words.clear()

            # 2-word check
            if corr is None and self.prev_words:
                phrase2 = f"{self.prev_words[-1][0]} {word}"
                if phrase2 in self.corrections:
                    corr = self.corrections[phrase2]
                    chars_to_delete = len(self.prev_words[-1][1]) + 1 + len(self.buffer) + 1
                    self.prev_words.clear()

        # 1-word check
        if corr is None and word in self.corrections:
            corr = self.corrections[word]
            chars_to_delete = len(self.buffer) + 1

        # Auto-capitalization at sentence start or new line
        if corr is None and is_sentence_start and word:
            capitalized = self._capitalize_first_alpha(self.buffer)
            if capitalized != self.buffer:
                if not any(c in word for c in ('@', ':', '/', '\\')):
                    corr = capitalized
                    chars_to_delete = len(self.buffer) + 1

        if corr is not None:
            # Preserve case (e.g. IM -> I'M, Im -> I'm)
            corr = self._preserve_case(self.buffer, corr)

            if is_sentence_start and corr and corr[0].islower():
                corr = corr[0].upper() + corr[1:]

            # Prevent feedback loops: if replacement is identical to current buffer, do nothing
            if corr == self.buffer:
                corr = None

        if corr is not None:
            # Set synthesis flag early in the listener thread to lock out subsequent physical keystrokes
            self.is_synthesizing = True
            # Queue the correction task for the background thread
            self.task_queue.put((chars_to_delete, corr, trigger, self.buffer))

            # Update history to reflect the replacement
            for _ in range(chars_to_delete):
                if self.history:
                    self.history.pop()
            self.history.extend(list(corr + trigger))

            if trigger == ' ':
                self.prev_words.append((word, corr))
                if len(self.prev_words) > 2:
                    self.prev_words.pop(0)
            else:
                self.prev_words.clear()
        else:
            if trigger == ' ':
                if word:
                    self.prev_words.append((word, self.buffer))
                    if len(self.prev_words) > 2:
                        self.prev_words.pop(0)
                else:
                    self.prev_words.clear()
            else:
                self.prev_words.clear()

        self.buffer = ""

        if trigger in _SENTENCE_BREAK_TRIGGERS:
            self.is_sentence_start = True
            self.prev_words.clear()
        elif preserve_sentence_start:
            self.is_sentence_start = True
        else:
            self.is_sentence_start = False

def run_mac_engine():
    # Enforce process singleton status to prevent concurrent instance loops
    enforce_singleton()

    engine = V26MacEngine(CORRECTIONS)
    logger.info("Loaded %d autocorrect rules for macOS.", len(CORRECTIONS))

    # Assert latency-critical status to completely bypass macOS App Nap and process throttling
    try:
        activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiated | NSActivityLatencyCritical,
            "Real-time keystroke autocorrection"
        )
        engine.activity_assertion = activity
        logger.info("Successfully asserted latency-critical status (App Nap disabled).")
    except Exception as e:
        logger.error("Failed to assert latency-critical status: %s", e)

    def on_press(key):
        try:
            # Suppress events that match our expected synthesized keystrokes (case-insensitive)
            char_rep = engine._get_key_char(key)
            if char_rep is not None:
                with engine.lock:
                    if engine.synthesized_queue and engine.synthesized_queue[0].lower() == char_rep.lower():
                        engine.synthesized_queue.pop(0)
                        return

            if engine.is_synthesizing:
                return
            
            # Check current modifier flags dynamically from the OS to ignore shortcuts
            try:
                flags = NSEvent.modifierFlags()
                if flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl):
                    engine.reset()
                    return
            except Exception as e:
                logger.error("Error checking modifier flags: %s", e)

            if hasattr(key, 'char') and key.char:
                if len(key.char) == 1:
                    # Ignore control character keypresses (ASCII < 32 except newline/tab)
                    if ord(key.char) < 32 and key.char not in ('\n', '\t', '\r'):
                        engine.reset()
                        return
                engine.handle_char(key.char)
            elif key == keyboard.Key.space:
                engine.handle_char(' ')
            elif key == keyboard.Key.enter:
                engine.handle_char('\n')
            elif key == keyboard.Key.tab:
                engine.handle_char('\t')
            elif key == keyboard.Key.backspace:
                engine.handle_backspace()
            elif key in (keyboard.Key.esc, keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
                         keyboard.Key.page_up, keyboard.Key.page_down, keyboard.Key.home, keyboard.Key.end, keyboard.Key.delete):
                engine.reset()
        except Exception as err:
            logger.error("Error handling key press: %s", err)

    def on_release(key):
        pass

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()

if __name__ == "__main__":
    run_mac_engine()
