import logging
import sys
import fcntl
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler

from Foundation import NSMaxRange, NSString
from Quartz import (
    CGEventGetIntegerValueField,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventSourceUnixProcessID,
    kCGKeyboardEventKeycode,
)
from pynput import keyboard
from AppKit import (
    NSActivityLatencyCritical,
    NSActivityUserInitiated,
    NSEvent,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSProcessInfo,
)

from mac_text_context import (
    ContextStatus,
    MacTextContext,
    is_sentence_start,
)

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

_TRIGGERS = frozenset((" ", ".", "!", "?", ",", "\n", "\t"))


@dataclass(frozen=True)
class CorrectionCandidate:
    source: str
    word: str
    replacement_template: str | None
    consumed_words: int
    local_sentence_start: bool


@dataclass(frozen=True)
class CorrectionProposal:
    source: str
    replacement: str
    word: str
    consumed_words: int
    sentence_start: bool


@dataclass(frozen=True)
class FallbackResult:
    applied: bool
    uncertain: bool = False


class V26MacEngine:
    def __init__(self, corrections: dict[str, str]):
        self.corrections = corrections
        self.buffer = ""
        self.prev_words = []
        self.history = []
        self.synthesized_queue = []
        self.context_confident = False

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
        if char in _TRIGGERS:
            raise ValueError("trigger characters must use prepare/commit_trigger")
        self.history.append(char)
        if len(self.history) > 1000:
            self.history = self.history[-500:]
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
        self.synthesized_queue.clear()
        self.context_confident = False

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
            if key.char == "\r":
                return "\n"
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

    def _local_sentence_start(self, source: str) -> bool:
        history_text = "".join(self.history)
        if not self.context_confident or not history_text.endswith(source):
            return False
        return is_sentence_start(history_text[:-len(source)] if source else history_text)

    def prepare_trigger(self, trigger: str) -> CorrectionCandidate | None:
        word = self.buffer.lower()
        if not word:
            return None

        replacement = None
        source = self.buffer
        consumed_words = 1

        if trigger == ' ':
            if len(self.prev_words) >= 2:
                phrase3 = f"{self.prev_words[-2][0]} {self.prev_words[-1][0]} {word}"
                if phrase3 in self.corrections:
                    replacement = self.corrections[phrase3]
                    source = (
                        f"{self.prev_words[-2][1]} "
                        f"{self.prev_words[-1][1]} {self.buffer}"
                    )
                    consumed_words = 3

            if replacement is None and self.prev_words:
                phrase2 = f"{self.prev_words[-1][0]} {word}"
                if phrase2 in self.corrections:
                    replacement = self.corrections[phrase2]
                    source = f"{self.prev_words[-1][1]} {self.buffer}"
                    consumed_words = 2

        if replacement is None and word in self.corrections:
            replacement = self.corrections[word]

        return CorrectionCandidate(
            source=source,
            word=word,
            replacement_template=replacement,
            consumed_words=consumed_words,
            local_sentence_start=self._local_sentence_start(source),
        )

    def finalize_candidate(
        self, candidate: CorrectionCandidate, sentence_start: bool
    ) -> CorrectionProposal | None:
        replacement = candidate.replacement_template

        if replacement is None and sentence_start:
            if not any(c in candidate.word for c in ('@', ':', '/', '\\')):
                capitalized = self._capitalize_first_alpha(self.buffer)
                if capitalized != self.buffer:
                    replacement = capitalized

        if replacement is None:
            return None

        replacement = self._preserve_case(self.buffer, replacement)
        if sentence_start and replacement and replacement[0].islower():
            replacement = replacement[0].upper() + replacement[1:]

        if replacement == candidate.source:
            return None

        return CorrectionProposal(
            source=candidate.source,
            replacement=replacement,
            word=candidate.word,
            consumed_words=candidate.consumed_words,
            sentence_start=sentence_start,
        )

    def local_source_matches(self, candidate: CorrectionCandidate) -> bool:
        return "".join(self.history).endswith(candidate.source)

    def commit_trigger(
        self,
        trigger: str,
        candidate: CorrectionCandidate | None,
        proposal: CorrectionProposal | None,
        applied: bool,
        stale: bool = False,
    ):
        raw_buffer = self.buffer
        if stale:
            self.reset()
            if trigger in (".", "!", "?", "\n"):
                self.history.append(trigger)
                self.context_confident = True
            return

        if applied and proposal is not None:
            history_text = "".join(self.history)
            if history_text.endswith(proposal.source):
                history_text = (
                    history_text[:-len(proposal.source)]
                    + proposal.replacement
                    + trigger
                )
            else:
                history_text = proposal.replacement + trigger
            self.history = list(history_text)
        else:
            self.history.append(trigger)

        if trigger == " " and raw_buffer:
            if applied and proposal is not None:
                if proposal.consumed_words > 1:
                    self.prev_words.clear()
                else:
                    self.prev_words.append((proposal.word, proposal.replacement))
            else:
                self.prev_words.append((raw_buffer.lower(), raw_buffer))
            if len(self.prev_words) > 2:
                self.prev_words = self.prev_words[-2:]
        else:
            self.prev_words.clear()

        self.buffer = ""
        if raw_buffer or trigger in (".", "!", "?", "\n"):
            self.context_confident = True
        if len(self.history) > 1000:
            self.history = self.history[-500:]

    def expect_synthetic(self, events: list[str]):
        self.synthesized_queue.extend(events)

    def consume_synthetic(self, event: str | None) -> bool:
        if (
            event is not None
            and self.synthesized_queue
            and self.synthesized_queue[0] == event
        ):
            self.synthesized_queue.pop(0)
            return True
        return False


def composed_character_count(value: str) -> int:
    string = NSString.stringWithString_(value)
    location = 0
    count = 0
    while location < string.length():
        character_range = string.rangeOfComposedCharacterSequenceAtIndex_(location)
        location = NSMaxRange(character_range)
        count += 1
    return count


class KeystrokeFallback:
    def __init__(self, controller):
        self.controller = controller

    def apply(
        self,
        engine: V26MacEngine,
        source: str,
        replacement: str,
        trigger: str,
    ) -> FallbackResult:
        delete_count = composed_character_count(source)
        expected = ["backspace"] * delete_count + list(replacement + trigger)
        engine.expect_synthetic(expected)
        mutated = False
        try:
            for _ in range(delete_count):
                mutated = True
                self.controller.tap(keyboard.Key.backspace)
            self.controller.type(replacement + trigger)
            return FallbackResult(applied=True)
        except Exception:
            engine.synthesized_queue.clear()
            logger.exception("Keystroke fallback failed while applying correction")
            return FallbackResult(applied=False, uncertain=mutated)


class TriggerSuppressor:
    def __init__(self, on_external_injected=None):
        self.suppress_current_key_down = False
        self.suppressed_key_codes = set()
        self.on_external_injected = on_external_injected

    def begin_key_down(self):
        self.suppress_current_key_down = False

    def suppress_current(self):
        self.suppress_current_key_down = True

    def intercept(self, event_type, event):
        source_pid = CGEventGetIntegerValueField(
            event, kCGEventSourceUnixProcessID
        )
        if source_pid:
            if (
                source_pid != os.getpid()
                and self.on_external_injected is not None
            ):
                self.on_external_injected()
            return event

        key_code = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if event_type == kCGEventKeyDown and key_code in self.suppressed_key_codes:
            return None
        if event_type == kCGEventKeyDown and self.suppress_current_key_down:
            self.suppress_current_key_down = False
            self.suppressed_key_codes.add(key_code)
            return None
        if event_type == kCGEventKeyUp and key_code in self.suppressed_key_codes:
            self.suppressed_key_codes.remove(key_code)
            return None
        return event

def run_mac_engine():
    # Enforce process singleton status to prevent concurrent instance loops
    enforce_singleton()

    engine = V26MacEngine(CORRECTIONS)
    text_context = MacTextContext()
    fallback = KeystrokeFallback(keyboard.Controller())
    suppressor = TriggerSuppressor(on_external_injected=engine.reset)
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

    def apply_trigger(trigger: str):
        candidate = engine.prepare_trigger(trigger)
        if candidate is None:
            engine.commit_trigger(trigger, None, None, applied=False)
            return

        inspection = text_context.inspect_before_caret(candidate.source)
        if inspection.status is ContextStatus.AVAILABLE:
            sentence_start = bool(inspection.sentence_start)
        elif inspection.status is ContextStatus.UNAVAILABLE:
            sentence_start = candidate.local_sentence_start
        else:
            logger.info(
                "[SKIPPED] Context is unsafe or stale: %s", inspection.reason
            )
            engine.commit_trigger(
                trigger, candidate, None, applied=False, stale=True
            )
            return

        proposal = engine.finalize_candidate(candidate, sentence_start)
        if proposal is None:
            engine.commit_trigger(
                trigger, candidate, None, applied=False
            )
            return

        applied = False
        stale = False
        suppress_original_trigger = False
        if inspection.status is ContextStatus.AVAILABLE:
            result = text_context.replace(
                inspection,
                proposal.source,
                proposal.replacement,
            )
            applied = result.applied
            if (
                not applied
                and result.status is ContextStatus.UNAVAILABLE
                and engine.local_source_matches(candidate)
            ):
                fallback_result = fallback.apply(
                    engine,
                    proposal.source,
                    proposal.replacement,
                    trigger,
                )
                applied = fallback_result.applied
                stale = fallback_result.uncertain
                suppress_original_trigger = applied
            elif not applied:
                stale = True
                logger.info("[SKIPPED] Accessibility replacement: %s", result.reason)
        elif engine.local_source_matches(candidate):
            fallback_result = fallback.apply(
                engine,
                proposal.source,
                proposal.replacement,
                trigger,
            )
            applied = fallback_result.applied
            stale = fallback_result.uncertain
            suppress_original_trigger = applied
        else:
            stale = True

        if suppress_original_trigger:
            suppressor.suppress_current()
        if applied:
            logger.info(
                "[SUCCESS] '%s' -> '%s' (Trigger: '%s')",
                proposal.source,
                proposal.replacement,
                trigger.replace("\n", "\\n").replace("\t", "\\t"),
            )
        engine.commit_trigger(
            trigger, candidate, proposal, applied=applied, stale=stale
        )

    def on_press(key, injected=False):
        try:
            char_rep = engine._get_key_char(key)
            if injected:
                engine.consume_synthetic(char_rep)
                return

            suppressor.begin_key_down()
            engine.synthesized_queue.clear()

            # Check current modifier flags dynamically from the OS to ignore shortcuts
            try:
                flags = NSEvent.modifierFlags()
                if flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption | NSEventModifierFlagControl):
                    engine.reset()
                    return
            except Exception as e:
                logger.error("Error checking modifier flags: %s", e)

            if char_rep is not None:
                if len(char_rep) == 1 and ord(char_rep) < 32:
                    if char_rep not in ("\n", "\t"):
                        engine.reset()
                        return
                if char_rep == "backspace":
                    engine.handle_backspace()
                elif char_rep in _TRIGGERS:
                    apply_trigger(char_rep)
                else:
                    engine.handle_char(char_rep)
            elif key == keyboard.Key.backspace:
                engine.handle_backspace()
            elif key in (keyboard.Key.esc, keyboard.Key.up, keyboard.Key.down, keyboard.Key.left, keyboard.Key.right,
                         keyboard.Key.page_up, keyboard.Key.page_down, keyboard.Key.home, keyboard.Key.end, keyboard.Key.delete):
                engine.reset()
        except Exception as err:
            logger.error("Error handling key press: %s", err)

    def on_release(key, injected=False):
        pass

    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release,
        darwin_intercept=suppressor.intercept,
    ) as listener:
        listener.join()

if __name__ == "__main__":
    run_mac_engine()
