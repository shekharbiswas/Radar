```
┌─────────────────────────────────────────────────────┐
│  VPS  (Hetzner / DigitalOcean / AWS)                │
│  Runs 24/7 independently of any browser             │
│                                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │  fetch_loop.py  (background service)         │    │
│  │                                              │    │
│  │  while market_open():                        │    │
│  │      fetch Angel One API (every 10s)         │    │
│  │      rank stocks                             │    │
│  │      write → SQLite DB                       │    │
│  │      sleep(10)                               │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │ writes                         │
│  ┌──────────────────▼──────────────────────────┐    │
│  │  signals.db  (SQLite)                        │    │
│  │  ├── ticks table    ← every stock every 10s  │    │
│  │  └── signals table  ← triggered events       │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │ reads                          │
│  ┌──────────────────▼──────────────────────────┐    │
│  │  app.py  (Streamlit — display only)          │    │
│  │  └── no fetch logic, just reads DB + renders │    │
│  └─────────────────────────────────────────────┘    │
└──────────────────┬──────────────────────────────────┘
                   │ HTTPS
        ┌──────────┴──────────┐
        │                     │
   📱 Mobile              💻 Any browser
   open/close             open anytime
   freely                 full history
```
