import requests
import time


def safe_get(url, headers=None, timeout=25, retries=3):

    for i in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
        except requests.exceptions.RequestException:
            pass

        time.sleep(1.5 * (i + 1))

    return None


def safe_post(url, json=None, headers=None, timeout=25, retries=3):

    for i in range(retries):
        try:
            r = requests.post(url, json=json, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r
        except requests.exceptions.RequestException:
            pass

        time.sleep(1.5 * (i + 1))

    return None
