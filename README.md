# Google & Apple Calendar Sync for Omarchy

A lightweight, theme-integrated calendar and clock status bar plugin for [Omarchy](https://omarchy.org/) (Hyprland + Quickshell).

Synchronize your private Google Calendar and Apple iCloud Calendar feeds directly into your Omarchy status bar calendar popup with interactive date picking, visual event indicator dots, and a clean agenda view.

![Omarchy Calendar Plugin](https://raw.githubusercontent.com/promaaa/Google-Apple-calendar-Omarchy/main/screenshot.png)

---

## ✨ Features

- **⚡ Lightweight & Fast**: Background multi-threaded event fetching with zero UI freezes.
- **🎨 Theme-Matched**: Seamlessly inherits your active Omarchy theme colors (`Color.accent`, `Color.foreground`, fonts, and borders).
- **📅 Interactive Month Grid**: Click any date to view scheduled events for that day.
- **🔴 Event Indicator Dots**: Visual markers on dates with scheduled events.
- **🔄 Auto & Manual Sync**: Syncs automatically on popup open and every 15 minutes in the background, with an instant manual sync button (`󰑐`).
- **🛡️ Private & Secure**: Works with your private read-only iCal (.ics / webcal) URLs — no OAuth apps, API keys, or browser logins required.
- **🔁 Recurring Events Support**: Handles daily, weekly, monthly, yearly `RRULE` repetitions and `EXDATE` exclusions.

---

## 🚀 Installation

Install directly using the Omarchy CLI:

```bash
omarchy plugin add https://github.com/promaaa/Google-Apple-calendar-Omarchy.git --enable
```

---

## ⚙️ Configuration

The plugin reads calendars from `~/.config/omarchy/calendars.json`. Create or edit this file:

```json
[
  {
    "name": "Google Calendar",
    "url": "https://calendar.google.com/calendar/ical/your_email%40gmail.com/private-xxxxxxxxxxxxxxxx/basic.ics",
    "color": "#4285f4",
    "enabled": true
  },
  {
    "name": "Apple iCloud",
    "url": "webcal://pXX-caldav.icloud.com/published/2/xxxxxxxx",
    "color": "#ff3b30",
    "enabled": true
  }
]
```

Changes to `calendars.json` are watched live and will reload automatically.

---

## 🔑 How to Get Your Calendar Feeds

### 🔵 Google Calendar
1. Open [Google Calendar](https://calendar.google.com/) in your browser.
2. In the left sidebar, hover over the calendar you want to sync $\rightarrow$ click the three dots $\rightarrow$ **Settings and sharing**.
3. Scroll down to the **"Integrate calendar"** section.
4. Copy the URL from **"Secret address in iCal format"**.
5. Paste it into your `~/.config/omarchy/calendars.json`.

### 🔴 Apple iCloud Calendar
1. Open [iCloud Calendar](https://www.icloud.com/calendar) or the macOS Calendar app.
2. Click the **Share** icon next to the calendar you want to sync.
3. Turn on **Public Calendar** (this generates a private sharing URL).
4. Copy the `webcal://...` link provided.
5. Paste it into your `~/.config/omarchy/calendars.json`.

---

## 📜 License

MIT License. Built for Omarchy.
