An absolutely elegant discord bot for a random server.
I'll be honest, 80% of code here is written by AI. But atleast I learnt the basics.

This bot automates voice enforcement, journaling habits, team systems, competitive programming updates, reminders, and mini-games. Use it if you've a study server.

---

## 🧠 Technologies Used

### Core

* **Python 3.9+**
* **discord.py** (slash commands, UI views, background tasks)
* **asyncio** (concurrent task handling)

### APIs & Integrations

* **Discord API**
* **Codeforces API** (contest updates)
* **LeetCode GraphQL API** (leetcode daily challenge updates)
* **GitHub REST API** (persistent state storage)
> OH, why did'nt you use SQL? Either I did'nt figure out how to on my free server, or it required premium to do so.

### Libraries

* `aiohttp` – async HTTP requests
* `python-dotenv` – environment variable management (we all lv privacy <3 )
* `pytz` – timezone handling
* `hashlib`, `mmh3` – deterministic hashing
* `json` – state serialization (Used in the watchers so the updates dont repeat and python knows when a new update appears)

### Infrastructure

* **GitHub as a lightweight database (Mainly coz i cannot link an SQL to the free server i use, so i used github as a workaround)[I now use a better server, but this is data that I am fine with going public]**
* **AIOHTTP web server** (This is the site to keep my bot alive, if you use a web-application server on your bot, such as render, then the initial setup is already on this)

---

## ✨ Features

### 🎥 Voice Channel Enforcement

* Monitors specific voice channels
* Requires users to enable **camera or stream**
* Automatic:

  * reminders
  * DMs
  * removal after configurable timeouts

---

### 📔 Daily Journal Reminder System

* User-configurable via slash commands
* Checks if users posted in their journal thread
* Sends reminders **daily at 9 PM IST**
* Prevents duplicate reminders per day

---

### 🧩 Competitive Programming Updates

#### 🏆 Codeforces

* Automatically posts upcoming contests
* Displays:

  * contest type
  * start time
  * duration
  * registration link
* Prevents duplicate posts using GitHub-backed state

#### 🧠 LeetCode

* Posts the **Daily Coding Challenge**
* Clean, structured embed:

  * problem title
  * difficulty
  * problem ID
  * direct solve link
* Handles GraphQL schema changes safely
* Fully debug-instrumented for reliability

---

### 👥 Team Systems

* Deterministic team assignment (hash-based)
* Perfectly balanced teams
* Persistent team roles
* Team point tracking stored on GitHub

---

### 🎯 Last Stand Mini-Game

* Turn-based survival game inside Discord
* Features:

  * joining system
  * attacks & defenses
  * lives
  * elimination
  * winner detection
* Fully persistent game state

---

### ⏰ Event & Custom Reminders

* Schedule reminders for future timestamps
* Automatically notify users **before** events start
* Integrated with voice and text channels

---

### 🌐 Reliability & Hosting

* Built-in web heartbeat server
* Background task recovery
* Safe JSON loading with auto-healing
* Extensive debug logging for all critical systems

---

## 📚 What I Learned

* How to use **discord.py** to create slash commands and interact with users
* How **background tasks** work in Discord bots
* How to **connect and use external APIs** (Codeforces, LeetCode)
* How to handle **API errors and unexpected responses**
* How to send **embeds, DMs, and automated messages**
* How to keep bot data persistent across restarts
* How to debug async code using logs and print statements
* How to be patient

---

## 🛠 Installation & Running

### 1️⃣ Clone the Repository

```bash
git clone https://github.com/your-username/your-repo-name.git
cd your-repo-name
```

---

### 2️⃣ Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 3️⃣ Create `.env` File

- Create the required json files
- Code will automatically create the schema for them, so don't bother.

```env
TOKEN=your_discord_bot_token

GH_TOKEN=your_github_token
GH_REPO_OWNER=your_github_username
GH_REPO_NAME=your_repo_name

GH_POINTS_FILE_PATH=points.json
GH_CF_FILE_PATH=codeforces.json
GH_LC_FILE_PATH=leetcode.json
```

> Create a github token from the settings, if you don't know how, learn it.
> ⚠️ The GitHub token must have **repository contents read/write permissions**.

---

### 4️⃣ Enable Required Discord Intents

In the Discord Developer Portal:

* ✅ Server Members Intent
* ✅ Message Content Intent
* ✅ Voice State Intent

---

### 5️⃣ Run the Bot

```bash
python vc_bot.py
```

You should see logs confirming:

* bot login
* task startup
* successful API connections

---

## 🏁 Final Notes
This project is pretty much a work in development, I plan to add more "games" to it, paired with features such as server moderation, voice tracking, using SQL instead of updating stuff directly on this github repo, and hopefully creating a good looking leaderboard using Pillow, and no i don't plan to use AI for these. 

Feel free to fork, extend, or adapt it to your own communities 🚀
