def filter_matches(event_type: str, event_filter: str) -> bool:
    if event_filter == "*":
        return True                        # wants everything
    if event_filter == event_type:
        return True                        # exact match, e.g. 'order.created'
    if event_filter.endswith(".*"):
        prefix = event_filter[:-1]         # 'order.*'  ->  'order.'
        return event_type.startswith(prefix)
    return False