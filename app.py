from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
import os
import json
import time

app = Flask(__name__)

# Chemins des fichiers de données
DATA_DIR = r"C:\Users\yvenl\OneDrive\Bureau\mon-api-flask\data"
GAMES_FILE = os.path.join(DATA_DIR, "games.json")
IMAGES_FILE = os.path.join(DATA_DIR, "image_urls.json")

# Crée les fichiers s'ils n'existent pas
os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(GAMES_FILE):
    with open(GAMES_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f, ensure_ascii=False, indent=4)
if not os.path.exists(IMAGES_FILE):
    with open(IMAGES_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f, ensure_ascii=False, indent=4)

def load_json_file(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {} if path.endswith('.json') else []

def save_json_file(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def setup_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)

def search_game(driver, game_name):
    search_box = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "store_nav_search_term"))
    )
    search_box.send_keys(game_name)
    search_box.send_keys(Keys.ENTER)

def click_first_game(driver):
    first_image = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, "div.col.search_capsule img"))
    )
    first_image.click()

def extract_image_url(driver):
    try:
        image_element = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#gameHeaderImageCtn img.game_header_image_full"))
        )
        return image_element.get_attribute("src")
    except TimeoutException:
        return None

def click_user_review(driver):
    try:
        review_links = WebDriverWait(driver, 10).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a.user_reviews_summary_row"))
        )
        if len(review_links) < 2:
            return False
        link_to_click = review_links[1]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", link_to_click)
        time.sleep(1)
        try:
            WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.user_reviews_summary_row")))
            link_to_click.click()
        except ElementClickInterceptedException:
            driver.execute_script("arguments[0].click();", link_to_click)
        except StaleElementReferenceException:
            updated_links = driver.find_elements(By.CSS_SELECTOR, "a.user_reviews_summary_row")
            if len(updated_links) >= 2:
                driver.execute_script("arguments[0].click();", updated_links[1])
        return True
    except TimeoutException:
        return False

def click_browse_reviews(driver):
    try:
        browse_reviews_div = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div#ViewAllReviewssummary"))
        )
        driver.execute_script("arguments[0].querySelector('a').click();", browse_reviews_div)
        return True
    except Exception:
        return False

def extract_reviews(driver, remaining_limit):
    extracted_reviews = []
    seen_ids = set()
    review_containers = driver.find_elements(By.CLASS_NAME, "apphub_Card")
    for container in review_containers:
        if len(extracted_reviews) >= remaining_limit:
            break
        try:
            recommended = container.find_element(By.CLASS_NAME, "title").text.strip()
            hours_played = container.find_element(By.CLASS_NAME, "hours").text.strip()
            date = container.find_element(By.CLASS_NAME, "date_posted").text.strip()
            comment_container = container.find_element(By.CLASS_NAME, "apphub_CardTextContent")
            comment = driver.execute_script(
                "return arguments[0].childNodes[arguments[0].childNodes.length - 1].textContent;",
                comment_container
            ).strip()

            review_id = f"{recommended}-{hours_played}-{date}-{comment[:30]}"
            if review_id not in seen_ids:
                seen_ids.add(review_id)
                extracted_reviews.append({
                    "Recommended": recommended,
                    "Hours Played": hours_played,
                    "Date Posted": date,
                    "Comment": comment
                })
        except Exception:
            pass
    return extracted_reviews
# Route d'accueil simple
@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "message": "Bienvenue sur l'API Steam Review Scraper. Utilisez la route POST /scrape avec un JSON contenant 'game_name'."
    })

@app.route('/scrape', methods=['POST'])
def scrape():
    data = request.get_json()
    if not data or "game_name" not in data:
        return jsonify({"error": "Missing 'game_name' in JSON body"}), 400

    game_name = data["game_name"]
    driver = setup_driver()

    try:
        driver.get("https://store.steampowered.com/")
        search_game(driver, game_name)
        click_first_game(driver)
        image_url = extract_image_url(driver)

        if not click_user_review(driver):
            return jsonify({"error": "User reviews section not found"}), 404
        if not click_browse_reviews(driver):
            return jsonify({"error": "Browse all reviews link not found"}), 404

        total_reviews = []
        count_limit = 5  # ajustable
        last_height = driver.execute_script("return document.body.scrollHeight")
        while len(total_reviews) < count_limit:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(3)
            new_reviews = extract_reviews(driver, count_limit - len(total_reviews))
            if not new_reviews:
                break
            total_reviews.extend(new_reviews)

            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        # --- Mise à jour des fichiers JSON ---
        games_data = load_json_file(GAMES_FILE)
        if game_name not in games_data:
            games_data[game_name] = []

        existing_reviews = {f"{r['Recommended']}-{r['Hours Played']}-{r['Date Posted']}-{r['Comment'][:30]}" for r in games_data[game_name]}
        for review in total_reviews:
            rid = f"{review['Recommended']}-{review['Hours Played']}-{review['Date Posted']}-{review['Comment'][:30]}"
            if rid not in existing_reviews:
                games_data[game_name].append(review)

        save_json_file(GAMES_FILE, games_data)

        image_urls = load_json_file(IMAGES_FILE)
        if image_url and image_url not in image_urls:
            image_urls.append(image_url)
            save_json_file(IMAGES_FILE, image_urls)

        return jsonify({
            "game_name": game_name,
            "image_url": image_url,
            "reviews": total_reviews
        })

    except Exception as e:
        return jsonify({"error": f"Exception occurred: {str(e)}"}), 500

    finally:
        driver.quit()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)), debug=True)
