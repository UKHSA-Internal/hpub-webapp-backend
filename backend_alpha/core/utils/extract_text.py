import logging
import re

# Setup logger
logger = logging.getLogger(__name__)


def extract_titles(text):
    # Split the input text into lines
    lines = text.splitlines()

    # Define patterns to recognize titles (e.g., certain keywords, formats, etc.)
    title_patterns = [
        r"\b(?:Poster|A3 poster|poster|Leaflet|Flyer|A3|A4|A5|Guide|Card|Checklist|Chart|Booklet|Summary|Report)\b",
        r"\b(?:Back to school|Protect yourself against|What to expect after|How to fit|Help is at hand)\b",
    ]

    # Combine patterns into a single regex pattern
    combined_pattern = re.compile("|".join(title_patterns), re.IGNORECASE)

    # Filter lines that match title patterns
    titles = [
        line.strip() for line in lines if line.strip() and combined_pattern.search(line)
    ]

    return titles


# Input text (shortened for example purposes)
text = """
Help is at hand Z-card
How to fit and fit check an ffp3 respirator - A3 poster
Hepatitis B risky business flyer (non gendered) b
The facts about Hepatitis a leaflet
When to use a surgical face make or ffp3 respirator - A3 poster
Help is at hand 2015 - support after someone may have died by suicide
Hepatitis B risky business postcard (non-gendered)b
Hepatitis A poster
Free NHS health check leaflet - Spanish
Keep your vaccine healthy cold chain fridge magnet
Fever? think menb vaccine A3 poster
Measles: don't let your child catch it flyer (for schools)
Immunisation: helps to protect your baby when they need it
Dementia health check leaflet - Gujarati
Meningitis - don't ignore the signs poster
Hepatitis B vaccine for at risk infants aide memoire
What to expect after vaccinations
Free NHS health check - audio CD
Protecting your baby against meningitis and septicaemia A3 poster
Think measles call ahead A3 poster
"""

# Extracted titles
titles = extract_titles(text)

# Print the extracted titles
for title in titles:
    logging.info(title)
