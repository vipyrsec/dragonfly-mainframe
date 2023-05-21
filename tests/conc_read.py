import queue
import threading
import time
from collections.abc import Generator
from typing import IO, Optional


class ConcurrentReader:
    """
    Class that allows non-blocking reads from a file-like object with an optional timeout.

    Once the `ConcurrentReader` is closed, either manually with
    `ConcurrentReader.close` or when a context manager exits, attempting to
    read from the instance will raise a `ValueError`

    Attributes:
        f: The file-like object to read from.
        timeout: A float representing the max time spent reading.
        poll_freq: A float representing the frequency in Hertz of polls of the file-like object.
        closed: A read-only bool indicating if the `ConcurrentReader` is closed.
    """

    def __init__(self, f: IO, timeout: float = 10, poll_freq: float = 1):
        """
        Initializes the instance with a given file-like object.

        Args:
            f: The file-like object to read from.
            timeout: A positive float representing the max time spent reading.
            poll_freq: A non-negative float representing the frequency in Hertz of polls of the file-like object.
        """

        self.f = f
        self.timeout = timeout
        self.poll_freq = poll_freq

        self._still_reading = True
        self._q = queue.Queue()

    @property
    def closed(self):
        return not self._still_reading

    def close(self):
        """Close the reader."""

        self._still_reading = False

    def _reader(self):
        while True:
            if not self._still_reading:
                break
            self._q.put(self.f.readline())
            time.sleep(1 / self.poll_freq)

    def __iter__(self) -> Generator[Optional[str], None, None]:
        """
        Reads the file-like object concurrently.

        Yields:
            A string if a line was read by the reader, None otherwise.

        Raises:
            ValueError: Attempted to read from a closed ConcurrentReader.
        """

        # Since `IO.readline` blocks until it can read a newline, we use
        # a separate thread in order to read from the file-like object. The
        # main thread keeps track of the elapsed time, and stops reading when
        # it exceeds `self.timeout`.

        if not self._still_reading:
            raise ValueError("Attempted to read from a closed ConcurrentReader")

        t = threading.Thread(target=self._reader)
        t.start()

        start = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - start

            if elapsed > self.timeout:
                self._still_reading = False
                return

            try:
                yield self._q.get_nowait()
            except queue.Empty:
                yield

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _tb):  # pyright: ignore
        self.close()
