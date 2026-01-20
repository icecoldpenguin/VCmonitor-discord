An absolutely elegant discord bot for a random server.

I'll be honest, 80% of code here is written by AI.

This bot automates voice enforcement, journaling habits, team systems, competitive programming updates, reminders, and mini-games.

---

## 🧠 Technologies Used

### Core

* **Python 3.9+**
* **discord.py** (slash commands, UI views, background tasks)
* **asyncio** (concurrent task handling)

### APIs & Integrations

* **Discord API**
* **Codeforces API** (contest updates)
* **LeetCode GraphQL API** (daily challenge updates)
* **GitHub REST API** (persistent state storage)

### Libraries

* `aiohttp` – async HTTP requests
* `python-dotenv` – environment variable management
* `pytz` – timezone handling (IST support)
* `hashlib`, `mmh3` – deterministic hashing
* `json` – state serialization

### Infrastructure

* **GitHub as a lightweight database**
* **AIOHTTP web server** (heartbeat for hosting platforms)

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

Through building this bot, I gained hands-on experience with:

* **Asynchronous programming** using `asyncio`
* Designing **idempotent background tasks**
* Handling **race conditions** in distributed systems
* Working with **unofficial / unstable APIs** (LeetCode GraphQL)
* Using **GitHub as a persistent datastore**
* Writing **production-grade Discord bots**
* Debugging long-running background tasks
* Designing extensible and modular bot architectures

Most importantly, I learned how to build systems that **fail loudly, recover safely, and scale cleanly**.

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

```env
TOKEN=your_discord_bot_token

# GitHub Persistence
GH_TOKEN=your_github_token
GH_REPO_OWNER=your_github_username
GH_REPO_NAME=your_repo_name

GH_POINTS_FILE_PATH=points.json
GH_CF_FILE_PATH=codeforces.json
GH_LC_FILE_PATH=leetcode.json
```

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

This project is built with **scalability, debuggability, and reliability** in mind.
It is actively designed to handle real-world Discord servers where silent failures are unacceptable.

Feel free to fork, extend, or adapt it to your own communities 🚀
