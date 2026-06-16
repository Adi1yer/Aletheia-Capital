from src.data.providers.aggregator import DataAggregator


def test_provider_chaos_fallback_and_quality_labels():
    agg = DataAggregator.__new__(DataAggregator)
    agg._quality_metrics = {"schema_failures": 0, "empty_payloads": 0}

    class Cache:
        def get_prices(self, *args, **kwargs):
            return None

        def set_prices(self, *args, **kwargs):
            return None

    class BadProvider:
        def get_prices(self, *args, **kwargs):
            return [{"bad": "shape"}]

    class EmptyProvider:
        def get_prices(self, *args, **kwargs):
            return []

    agg.cache = Cache()
    agg.providers = [BadProvider(), EmptyProvider()]
    out = agg.get_prices("AAPL", "2024-01-01", "2024-02-01")
    assert out == []
    q = agg.data_quality_score()
    assert q["schema_failures"] >= 1
    assert q["empty_payloads"] >= 1

