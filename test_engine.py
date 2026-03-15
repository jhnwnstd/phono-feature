#!/usr/bin/env python3
"""
Test script for the phonology engine (no GUI required).

This script demonstrates core engine functionality without launching the GUI.
Use this to verify your installation and understand the API.

Usage:
    python test_engine.py
"""

from engine.feature_engine import FeatureEngine
from engine.geometry import GeometryAnalyzer


def print_section(title):
    """Print a formatted section header."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


def test_basic_operations():
    """Test basic engine operations."""
    print_section("Basic Engine Operations")

    # Load inventory
    engine = FeatureEngine()
    print("\nLoading Hayes English inventory...")
    engine.load_inventory("config/hayes_english.json")
    print(f"✓ Loaded: {engine.metadata['name']}")
    print(f"  Segments: {len(engine.segments)}")
    print(f"  Features: {len(engine.features)}")

    # Get segment features
    print("\n1. Get features for segment 'b':")
    features = engine.get_segment_features("b")
    for feat, val in sorted(features.items()):
        print(f"   {feat:15s} = {val}")

    # Find segments by features
    print("\n2. Find voiced stops (Voice:+, Continuant:-):")
    voiced_stops = engine.find_segments({"Voice": "+", "Continuant": "-"})
    print(f"   Found: {', '.join(voiced_stops)}")

    # Compute natural class
    print("\n3. Natural class for [b, d, ɡ]:")
    bundle, is_minimal = engine.compute_natural_class(["b", "d", "ɡ"])
    print("   Characterizing features:")
    for feat, val in sorted(bundle.items()):
        print(f"     {feat:15s} = {val}")
    print(f"   Minimal bundle: {'Yes' if is_minimal else 'No'}")

    # Calculate distances
    print("\n4. Phonological distances:")
    pairs = [("b", "d"), ("b", "p"), ("b", "m"), ("b", "v")]
    for seg1, seg2 in pairs:
        dist = engine.segment_distance(seg1, seg2)
        print(f"   {seg1} ↔ {seg2}: {dist} features")

    # Find nearest neighbors
    print("\n5. Nearest neighbors to 'b':")
    neighbors = engine.find_nearest_segments("b", n=5)
    for neighbor, distance in neighbors:
        print(f"   {neighbor} (distance: {distance})")

    # Inventory statistics
    print("\n6. Inventory statistics:")
    stats = engine.get_inventory_stats()
    print(f"   Total segments: {stats['segment_count']}")
    print(f"   Total features: {stats['feature_count']}")
    print(f"   Contrastive features: {stats['contrastive_features']}")
    print(f"   Avg pairwise distance: {stats['avg_feature_distance']:.2f}")

    return engine


def test_geometry_analysis(engine):
    """Test feature geometry inference."""
    print_section("Feature Geometry Analysis")

    print("\nInferring feature geometry...")
    print("(This may take a moment - running permutation tests...)")

    analyzer = GeometryAnalyzer(engine)
    analyzer.analyze()

    print("\n✓ Geometry analysis complete!")

    dependencies = analyzer.get_dependency_summary()

    print(f"\nFound {len(dependencies)} feature dependencies:")
    print(
        f"\n{'Child Feature':<20} {'Parent Feature':<20} {'Coverage':<10} {'Confidence':<12}"
    )
    print("-" * 70)

    for dep in dependencies[:10]:  # Show top 10
        child = dep["child"]
        parent = dep["parent"]
        coverage = f"{dep['coverage']:.2%}"
        confidence = dep["confidence"].upper()
        print(f"{child:<20} {parent:<20} {coverage:<10} {confidence:<12}")

    if len(dependencies) > 10:
        print(f"\n... and {len(dependencies) - 10} more dependencies")

    # Show high-confidence dependencies
    high_conf = [d for d in dependencies if d["confidence"] == "high"]
    if high_conf:
        print(f"\n\nHigh-confidence dependencies ({len(high_conf)}):")
        for dep in high_conf:
            print(f"  • [{dep['child']}] depends on [{dep['parent']}]")
            print(
                f"    Coverage: {dep['coverage']:.2%}, p-value: {dep['p_value']:.4f}"
            )


def test_natural_class_examples():
    """Test various natural class computations."""
    print_section("Natural Class Examples")

    engine = FeatureEngine()
    engine.load_inventory("config/hayes_english.json")

    examples = [
        (["b", "d", "ɡ"], "Voiced stops"),
        (["p", "t", "k"], "Voiceless stops"),
        (["m", "n", "ŋ"], "Nasals"),
        (["f", "v", "s", "z"], "Fricatives (subset)"),
        (["l"], "Lateral"),
    ]

    for segments, description in examples:
        print(f"\n{description}: {', '.join(segments)}")
        bundle, is_minimal = engine.compute_natural_class(segments)

        if bundle:
            features_str = ", ".join(
                f"{k}:{v}" for k, v in sorted(bundle.items())
            )
            print(f"  Features: {features_str}")
        else:
            print("  Features: (none required)")

        # Verify the bundle picks out exactly these segments
        found = engine.find_segments(bundle)
        if set(found) == set(segments):
            print("  ✓ Exact match")
        else:
            extra = set(found) - set(segments)
            if extra:
                print(f"  ⚠ Also includes: {', '.join(extra)}")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("  PHONOLOGY ENGINE TEST SUITE")
    print("=" * 60)

    try:
        # Test basic operations
        engine = test_basic_operations()

        # Test natural class examples
        test_natural_class_examples()

        # Test geometry analysis
        test_geometry_analysis(engine)

        print_section("All Tests Complete")
        print("\n✓ Engine is working correctly!")
        print("\nTo launch the GUI, run:")
        print("  python main.py")

    except Exception as e:
        print(f"\n✗ Error during testing: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
