from collections.abc import Iterator


class EventBroadcaster:
    def initial_stream(self) -> Iterator[str]:
        yield "event: connected\ndata: {}\n\n"
