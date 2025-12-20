# Dublin Rental Hunter

A Python application that monitors Dublin rental property websites and sends notifications when new listings matching your criteria are found.

## Features

- Scrapes multiple rental websites (Daft.ie, Rent.ie, MyHome.ie)
- Filters listings based on configurable criteria (price, bedrooms, location)
- Sends notifications via Telegram and/or Email
- Stores listings in SQLite database to avoid duplicate notifications
- Runs continuously with configurable scrape intervals

## Installation

1. Clone this repository
2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and configure your credentials
5. Edit `config/config.yaml` to set your search criteria

## Configuration

Edit `config/config.yaml` to customize:
- Price range
- Number of bedrooms
- Locations to search
- Property types
- Notification preferences
- Scrape interval

## Usage

```bash
python main.py
```

## License

MIT
