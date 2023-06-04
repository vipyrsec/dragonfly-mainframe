import queue
import sys
import threading
import time
from collections.abc import Generator
from typing import IO, Optional


class ConcurrentReader:
    """
    Class that allows non-blocking reads from a file-like object with an optional timeout.

    An instance of ConcurrentReader will continously read from the file-like object until it is closed.

    Attributes:
        f: The file-like object to read from.
        timeout: A float representing the max time spent reading.
        poll_freq: A float representing the frequency in Hertz of polls of the file-like object.
        quiet: A bool indicating whether or not to mirror the read data to stderr.
    """

    def __init__(self, f: IO, timeout: float = 10, poll_freq: float = 1, quiet: bool = False):
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
        self._queue = queue.Queue()
        # use a daemon thread so that we can exit even if a readline call is blocking us
        self._reader_thread = threading.Thread(target=self._reader, daemon=True)
        self.quiet = quiet

    @property
    def closed(self):
        return not self._still_reading

    def close(self):
        """Close the reader."""

        self._still_reading = False

    def _reader(self):
        while self._still_reading:
            line = self.f.readline()
            if line != "":
                if not self.quiet:
                    print(f"SERVER: {line!r}", file=sys.stderr)
                self._queue.put(line)
            time.sleep(1 / self.poll_freq)

    def __iter__(self) -> Generator[Optional[str], None, None]:
        """
        Reads the file-like object concurrently.

        Yields:
            A string if a line was read by the reader, None otherwise.
        """

        # Since `IO.readline` blocks until it can read a newline, we use
        # a separate thread in order to read from the file-like object. The
        # main thread keeps track of the elapsed time, and stops reading when
        # it exceeds `self.timeout`.

        self._reader_thread.start()

        start = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - start

            if self.timeout > 0 and elapsed > self.timeout:
                return

            try:
                yield self._queue.get_nowait()
            except queue.Empty:
                yield

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _tb):  # pyright: ignore
        self.close()
