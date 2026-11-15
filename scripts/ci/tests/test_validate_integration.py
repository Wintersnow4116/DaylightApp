import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_integration import APPS, CONFIGURATIONS, validate_settings, validate_spec


class IntegrationValidationTests(unittest.TestCase):
    def spec(self):
        targets = {}
        schemes = {}
        for name, (platform, _, _, _) in APPS.items():
            targets[name] = {"type": "application", "platform": platform,
                             "dependencies": [{"package": "DaylightCore", "product": "DaylightCore"}]}
            schemes[name] = {"build": {"targets": {name: "all"}}}
        targets["DaylightUITests"] = {
            "type": "bundle.ui-testing", "platform": "iOS",
            "settings": {"base": {"TEST_TARGET_NAME": "DaylightIOS"}},
            "dependencies": [{"target": "DaylightIOS"}]
        }
        schemes["DaylightUITests"] = {"test": {"config": "UITesting", "targets": [{"name": "DaylightUITests"}]}}
        return {"configs": {"Debug": "debug", "Release": "release", "UITesting": "debug"},
                "packages": {"DaylightCore": {"path": "SharedCore"}},
                "options": {"deploymentTarget": {"iOS": "17.0", "watchOS": "10.0"}},
                "targets": targets, "schemes": schemes}

    def manifest(self):
        return {"products": [{"name": "DaylightCore", "targets": ["DaylightCore"]}],
                "targets": [{"name": "DaylightCore", "type": "regular"}]}

    def settings(self, target, configuration):
        _, key, minimum, bundle = APPS[target]
        isolated = target == "DaylightIOS" and configuration == "UITesting"
        return [{"target": target, "buildSettings": {
            key: minimum, "CONFIGURATION": configuration,
            "PRODUCT_BUNDLE_IDENTIFIER": bundle + (".uitesting" if isolated else ""),
            "SWIFT_ACTIVE_COMPILATION_CONDITIONS": "DEBUG DAYLIGHT_UI_TESTING" if isolated else "",
            "CODE_SIGNING_ALLOWED": "NO"
        }}]

    def test_valid_native_spec_and_all_six_resolved_configurations(self):
        validate_spec(self.spec(), self.manifest())
        for target in APPS:
            for configuration in CONFIGURATIONS:
                with self.subTest(target=target, configuration=configuration):
                    validate_settings(self.settings(target, configuration), target, configuration)

    def test_each_app_requires_its_own_local_product_dependency(self):
        for target in APPS:
            spec = self.spec()
            spec["targets"][target]["dependencies"] = []
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "direct DaylightCore"):
                validate_spec(spec, self.manifest())

    def test_release_cannot_be_a_debug_type_configuration(self):
        spec = self.spec()
        spec["configs"]["Release"] = "debug"
        with self.assertRaisesRegex(ValueError, "configuration types"):
            validate_spec(spec, self.manifest())

    def test_remote_package_or_wrong_export_is_rejected(self):
        spec = self.spec()
        spec["packages"]["DaylightCore"] = {"url": "https://example.invalid/package"}
        with self.assertRaisesRegex(ValueError, "local SharedCore"):
            validate_spec(spec, self.manifest())
        with self.assertRaisesRegex(ValueError, "export"):
            validate_spec(self.spec(), {"products": [], "targets": []})

    def test_cross_app_dependency_and_extra_application_are_rejected(self):
        spec = self.spec()
        spec["targets"]["DaylightWatch"]["dependencies"].append({"target": "DaylightIOS"})
        with self.assertRaisesRegex(ValueError, "must not depend"):
            validate_spec(spec, self.manifest())
        spec = self.spec()
        spec["targets"]["Desktop"] = {"type": "application", "platform": "macOS"}
        with self.assertRaisesRegex(ValueError, "Only the existing"):
            validate_spec(spec, self.manifest())

    def test_wrong_platform_minimum_and_ui_target_are_rejected(self):
        original = self.spec()
        for mutation in ("platform", "minimum", "ui"):
            spec = copy.deepcopy(original)
            if mutation == "platform": spec["targets"]["DaylightWatch"]["platform"] = "iOS"
            elif mutation == "minimum": spec["options"]["deploymentTarget"]["iOS"] = "16.0"
            else: spec["targets"]["DaylightUITests"]["settings"]["base"]["TEST_TARGET_NAME"] = "DaylightWatch"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                validate_spec(spec, self.manifest())

    def test_resolved_override_wrong_bundle_flag_or_signing_is_rejected(self):
        for key, value in [("IPHONEOS_DEPLOYMENT_TARGET", "16.0"),
                           ("PRODUCT_BUNDLE_IDENTIFIER", "org.example.wrong"),
                           ("SWIFT_ACTIVE_COMPILATION_CONDITIONS", "DAYLIGHT_UI_TESTING"),
                           ("CODE_SIGNING_ALLOWED", "YES"), ("CONFIGURATION", "Release")]:
            rows = self.settings("DaylightIOS", "Debug")
            rows[0]["buildSettings"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_settings(rows, "DaylightIOS", "Debug")

    def test_missing_ambiguous_or_nonisolated_ui_settings_are_rejected(self):
        rows = self.settings("DaylightIOS", "UITesting")
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            validate_settings(rows + rows, "DaylightIOS", "UITesting")
        with self.assertRaises(ValueError):
            validate_settings([], "DaylightWatch", "Release")
        rows[0]["buildSettings"]["SWIFT_ACTIVE_COMPILATION_CONDITIONS"] = "DEBUG"
        with self.assertRaisesRegex(ValueError, "routing flag"):
            validate_settings(rows, "DaylightIOS", "UITesting")

    def test_deployment_comparison_does_not_trim_significant_zeroes(self):
        rows = self.settings("DaylightIOS", "Debug")
        rows[0]["buildSettings"]["IPHONEOS_DEPLOYMENT_TARGET"] = "17"
        validate_settings(rows, "DaylightIOS", "Debug")
        for target, key, invalid in [("DaylightIOS", "IPHONEOS_DEPLOYMENT_TARGET", "170.0"),
                                     ("DaylightWatch", "WATCHOS_DEPLOYMENT_TARGET", "1.0"),
                                     ("DaylightWatch", "WATCHOS_DEPLOYMENT_TARGET", "10.1"),
                                     ("DaylightIOS", "IPHONEOS_DEPLOYMENT_TARGET", "17.0.0.1")]:
            rows = self.settings(target, "Release")
            rows[0]["buildSettings"][key] = invalid
            with self.subTest(target=target, invalid=invalid), self.assertRaises(ValueError):
                validate_settings(rows, target, "Release")


if __name__ == "__main__":
    unittest.main()
