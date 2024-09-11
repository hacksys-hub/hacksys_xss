import requests
from bs4 import BeautifulSoup
import argparse
import os
import logging
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import sleep
from termcolor import colored
import json
from fpdf import FPDF
import asyncio
import aiohttp
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller
import concurrent.futures

# Configure logging
logging.basicConfig(filename='xss_exploitation.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Branding
BRANDING = "HackSys Advanced XSS Exploitation Tool"

# Define the parser
parser = argparse.ArgumentParser(description='Advanced XSS Exploitation Tool - HackSys')
parser.add_argument('-u', '--url', help='Single URL to scan')
parser.add_argument('-l', '--list', help='File containing list of URLs to scan')
parser.add_argument('-p', '--payloads', help='File containing list of payloads to use')
parser.add_argument('-o', '--output', help='File to save results')
parser.add_argument('-a', '--user-agent', default='Mozilla/5.0', help='User-Agent to use for requests')
parser.add_argument('--headers', help='Additional headers to use for requests in key:value format, comma-separated')
parser.add_argument('--rate-limit', type=int, default=5, help='Rate limit for requests per second')
parser.add_argument('-t', '--threads', type=int, default=5, help='Number of concurrent threads')
parser.add_argument('-v', '--verbose', type=int, choices=range(6), default=1, help='Verbose mode (0-5), default is 1')
parser.add_argument('--config', help='Configuration file in JSON format')
parser.add_argument('--filter', help='Keyword filter for URLs')
parser.add_argument('--report', help='Generate report in specified format (HTML, CSV, PDF)')
parser.add_argument('-up', '--update', action='store_true', help='Update the tool to the latest version')

args = parser.parse_args()

# Set logging level based on verbosity
verbose_levels = [logging.ERROR, logging.WARNING, logging.INFO, logging.DEBUG]
logging.getLogger().setLevel(verbose_levels[min(args.verbose, len(verbose_levels) - 1)])

# Print branding
if args.verbose > 0:
    print(colored(BRANDING, 'cyan'))

# Obtain permission
def check_permission():
    print(colored("Ensure you have permission to scan the target URLs. Continue? (y/n): ", 'red'), end='')
    response = input().lower()
    if response != 'y':
        print(colored("Permission denied by user. Exiting...", 'red'))
        exit()

# Load configuration file
def load_config(config_file):
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        if args.verbose > 1:
            print(colored(f"Loaded configuration from {config_file}", 'blue'))
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found: {config_file}")
        return {}
    except json.JSONDecodeError:
        logging.error(f"Invalid JSON format in configuration file: {config_file}")
        return {}

# Parse headers from configuration
def parse_headers(header_string):
    headers = {}
    if header_string:
        for header in header_string.split(','):
            try:
                key, value = header.split(':', 1)
                headers[key.strip()] = value.strip()
            except ValueError:
                logging.error(f"Header parsing error with: {header}")
    return headers

# Filter URLs based on user-defined criteria
def filter_urls(urls, keyword):
    filtered_urls = [url for url in urls if keyword in url]
    if args.verbose > 2:
        print(colored(f"Filtered URLs: {filtered_urls}", 'blue'))
    return filtered_urls

# Set up Chrome WebDriver
def setup_chrome_driver():
    chromedriver_autoinstaller.install()
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    service = Service()
    return webdriver.Chrome(service=service, options=chrome_options)

# Get page content using Chrome WebDriver
def get_page_content(url):
    driver = setup_chrome_driver()
    try:
        driver.get(url)
        sleep(3)
        return driver.page_source
    finally:
        driver.quit()

# Enhanced XSS scanning
async def scan_xss(url, headers):
    try:
        if args.verbose > 2:
            print(colored(f"Scanning {url} for XSS injection points...", 'blue'))
        content = await asyncio.to_thread(get_page_content, url)  # Run in a separate thread
        soup = BeautifulSoup(content, 'html.parser')
        injection_points = [input_field.get('name') for form in soup.find_all('form') for input_field in form.find_all('input') if 'name' in input_field.attrs]
        if args.verbose > 3:
            print(colored(f"Injection points found: {injection_points}", 'blue'))
        return injection_points
    except Exception as e:
        logging.error(f"Error scanning {url}: {e}")
        return []

# Generate payloads
def generate_payloads(payloads_file):
    try:
        if args.verbose > 2:
            print(colored(f"Generating payloads from {payloads_file}...", 'blue'))
        with open(payloads_file, 'r') as f:
            payloads = f.readlines()
        return [payload.strip() for payload in payloads]
    except FileNotFoundError:
        logging.error(f"Payload file not found: {payloads_file}")
        return []
    except Exception as e:
        logging.error(f"Error generating payloads: {e}")
        return []

# Fuzz payloads with rate limiting and advanced analysis
async def fuzz_payload(url, injection_point, payload, headers, rate_limit):
    try:
        await asyncio.sleep(1 / rate_limit)
        params = {injection_point: payload}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=10) as response:
                content = await response.text()
                if args.verbose > 4:
                    print(colored(f"Testing payload {payload} on {url} at {injection_point}", 'blue'))
                if any(keyword in content.lower() for keyword in ['<script>', 'alert(', 'onerror=', 'document.cookie', 'eval(', 'javascript:']):
                    await log_request_response(url, params, response)
                    return True
        return False
    except Exception as e:
        logging.error(f"Error fuzzing {url}: {e}")
        return False

# Log request and response
async def log_request_response(url, params, response):
    try:
        with open('requests_responses.log', 'a') as f:
            f.write(f"URL: {url}\n")
            f.write(f"Params: {params}\n")
            f.write(f"Response Status: {response.status}\n")
            f.write(f"Response Body: {response.text[:500]}\n")  # Limit to 500 chars
            f.write("="*50 + "\n")
    except Exception as e:
        logging.error(f"Error logging request/response: {e}")

# Main exploit function with enhanced reporting
async def exploit_xss(url, payloads, headers, output_file):
    injection_points = await scan_xss(url, headers)
    if not injection_points:
        print(colored(f"No injection points found for {url}", 'yellow'))
        return
    for injection_point in injection_points:
        for payload in payloads:
            if await fuzz_payload(url, injection_point, payload, headers, args.rate_limit):
                result = f"{url}?{injection_point}={payload}  with injection point {injection_point}"
                print(colored(f"XSS vulnerability found: ", 'red') + colored(result, 'green'))
                logging.info(result)
                save_result(output_file, result)

# Save results with exception handling
def save_result(output_file, result):
    if output_file:
        try:
            with open(output_file, 'a') as f:
                f.write(result + '\n')
        except Exception as e:
            logging.error(f"Error writing to output file {output_file}: {e}")

# Enhanced reporting functionality
def generate_report(output_file, report_format):
    if report_format.lower() == 'html':
        generate_html_report(output_file)
    elif report_format.lower() == 'csv':
        generate_csv_report(output_file)
    elif report_format.lower() == 'pdf':
        generate_pdf_report(output_file)
    else:
        print(colored("Unsupported report format. Supported formats: HTML, CSV, PDF.", 'red'))

def generate_html_report(output_file):
    try:
        with open(output_file, 'r') as f:
            results = f.readlines()
        html_content = "<html><body><h1>XSS Exploitation Results</h1><ul>"
        for result in results:
            html_content += f"<li>{result.strip()}</li>"
        html_content += "</ul></body></html>"
        with open('report.html', 'w') as f:
            f.write(html_content)
        print(colored("HTML report generated successfully.", 'green'))
    except Exception as e:
        logging.error(f"Error generating HTML report: {e}")

def generate_csv_report(output_file):
    try:
        import csv
        with open(output_file, 'r') as f:
            results = f.readlines()
        with open('report.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["URL"])
            for result in results:
                writer.writerow([result.strip()])
        print(colored("CSV report generated successfully.", 'green'))
    except Exception as e:
        logging.error(f"Error generating CSV report: {e}")

def generate_pdf_report(output_file):
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt="XSS Exploitation Results", ln=True, align='C')
        with open(output_file, 'r') as f:
            results = f.readlines()
        for result in results:
            pdf.multi_cell(0, 10, txt=result.strip())
        pdf.output("report.pdf")
        print(colored("PDF report generated successfully.", 'green'))
    except Exception as e:
        logging.error(f"Error generating PDF report: {e}")

# Main execution
async def main():
    if args.update:
        subprocess.run(["git", "pull"], check=True)
        print(colored("Tool updated to the latest version.", 'green'))
        return
    
    check_permission()
    
    urls = []
    if args.url:
        urls.append(args.url)
    elif args.list:
        try:
            with open(args.list, 'r') as f:
                urls = [line.strip() for line in f]
        except FileNotFoundError:
            logging.error(f"URL list file not found: {args.list}")
    
    if args.filter:
        urls = filter_urls(urls, args.filter)

    headers = parse_headers(args.headers)

    if args.payloads:
        payloads = generate_payloads(args.payloads)
    else:
        payloads = ["<script>alert('XSS')</script>"]

    tasks = []
    with ThreadPoolExecutor(max_workers=args.threads) as executor:
        loop = asyncio.get_event_loop()
        for url in urls:
            tasks.append(loop.create_task(exploit_xss(url, payloads, headers, args.output)))
        await asyncio.gather(*tasks)

    if args.report:
        generate_report(args.output, args.report)

# Run the main function
if __name__ == "__main__":
    asyncio.run(main())
