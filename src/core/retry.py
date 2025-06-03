import time
import functools
import random


def retry_on_exception(max_retries=3, base_delay=1, max_delay=10, backoff=2, jitter=True):
    """
    Retry decorator with exponential backoff.

    :param max_retries: Number of retries before failing.
    :param base_delay: Initial wait time.
    :param max_delay: Maximum wait time.
    :param backoff: Multiplier for exponential delay.
    :param jitter: If True, adds random jitter to delay.
    :return: Wrapped function with retry behavior.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            delay = base_delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    sleep_time = delay + random.uniform(0, 1) if jitter else delay
                    sleep_time = min(sleep_time, max_delay)
                    print(f"⚠️ Retry {attempt + 1}/{max_retries} after error: {e}. Retrying in {sleep_time:.2f}s")
                    time.sleep(sleep_time)
                    delay *= backoff
        return wrapper
    return decorator