```
┌─────────────────────────────────────────────────────┐
│  VPS  (Hetzner / DigitalOcean / AWS)                │
│  Runs 24/7 on any device                            │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  fetch_loop.py  (background service)         │    │
│  │                                              │    │
│  │  while market_open():                        │    │
│  │      fetch xxxxx API (every 10s)             │    │
│  │      rank stocks                             │    │
│  │      write →   DB                            │    │
│  │      sleep(10)                               │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │ writes                         │
│  ┌──────────────────▼──────────────────────────┐    │
│  │  signals.db                                 │    │
│  │  ├── ticks table    ← every stock every xx s │    │
│  │  └── signals table  ← triggered events       │    │
│  └──────────────────┬──────────────────────────┘    │
│                     │ reads                          │
│  ┌──────────────────▼──────────────────────────┐    │
│  │  app.py  (display only)          │    │
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

check original repo for full product simulation
