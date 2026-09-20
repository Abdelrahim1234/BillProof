from billproof.models import MedicareBenchmark, RegionalBenchmark, ServiceBundle


async def get_medicare_benchmark(db, hospital_id: str, code_type: str, code: str) -> MedicareBenchmark | None:
    doc = await db["medicare_benchmarks"].find_one(
        {"hospital_id": hospital_id, "code_type": code_type, "code": code, "suppressed": False}
    )
    return MedicareBenchmark.from_doc(doc) if doc else None


async def search_regional_benchmarks(
    db, *, geography_type: str, geography_code: str, service_code: str, code_type: str
) -> list[RegionalBenchmark]:
    docs = await db["regional_benchmarks"].find(
        {
            "geography_type": geography_type,
            "geography_code": geography_code,
            "service_code": service_code,
            "code_type": code_type,
            "suppressed": False,
        }
    ).to_list()
    return [RegionalBenchmark.from_doc(d) for d in docs]


async def get_regional_benchmark(db, benchmark_id: str) -> RegionalBenchmark | None:
    doc = await db["regional_benchmarks"].find_one({"_id": benchmark_id})
    return RegionalBenchmark.from_doc(doc) if doc else None


async def any_regional_benchmark(db, code_type: str, service_code: str) -> RegionalBenchmark | None:
    doc = await db["regional_benchmarks"].find_one({"code_type": code_type, "service_code": service_code})
    return RegionalBenchmark.from_doc(doc) if doc else None


async def get_service_bundle_by_key(db, service_key: str) -> ServiceBundle | None:
    doc = await db["service_bundles"].find_one({"normalized_service_key": service_key})
    return ServiceBundle.from_doc(doc) if doc else None


async def upsert_service_bundle(db, bundle: ServiceBundle) -> None:
    await db["service_bundles"].update_one({"_id": bundle.id}, {"$set": bundle.to_set()}, upsert=True)
