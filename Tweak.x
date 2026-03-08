#import <Foundation/Foundation.h>
#import <objc/runtime.h>

// The bundle ID baked into the resigned IPA (what the OS sees)
static NSString *const kFakeBundleID = @"annnekkk.modified.tailscale";
// The original bundle ID the app binary expects internally
static NSString *const kRealBundleID = @"io.tailscale.ipn.ios";

// Replace every occurrence of the fake ID with the real one
static NSString *spoof(NSString *s) {
    if (!s) return s;
    if ([s isEqualToString:kFakeBundleID]) return kRealBundleID;
    // Handle suffixed IDs like annnekkk.modified.tailscale.network-extension
    if ([s hasPrefix:kFakeBundleID]) {
        return [kRealBundleID stringByAppendingString:[s substringFromIndex:kFakeBundleID.length]];
    }
    return s;
}

// ── NSBundle ──────────────────────────────────────────────────────────────────

%hook NSBundle

- (NSString *)bundleIdentifier {
    return spoof(%orig);
}

- (NSDictionary *)infoDictionary {
    NSMutableDictionary *info = [%orig mutableCopy];
    if (!info) return %orig;
    if (info[@"CFBundleIdentifier"])
        info[@"CFBundleIdentifier"] = spoof(info[@"CFBundleIdentifier"]);
    if (info[@"WKAppBundleIdentifier"])
        info[@"WKAppBundleIdentifier"] = spoof(info[@"WKAppBundleIdentifier"]);
    if (info[@"NSExtension"][@"NSExtensionAttributes"][@"WKAppBundleIdentifier"])
        ((NSMutableDictionary *)info[@"NSExtension"][@"NSExtensionAttributes"])[@"WKAppBundleIdentifier"] =
            spoof(info[@"NSExtension"][@"NSExtensionAttributes"][@"WKAppBundleIdentifier"]);
    return [info copy];
}

- (id)objectForInfoDictionaryKey:(NSString *)key {
    id val = %orig;
    if ([key isEqualToString:@"CFBundleIdentifier"] && [val isKindOfClass:[NSString class]])
        return spoof(val);
    return val;
}

%end

// ── NSUserDefaults / App Groups ───────────────────────────────────────────────
// Tailscale uses an App Group to share data with its extensions.
// The group ID is derived from the bundle ID, so we spoof it too.

%hook NSUserDefaults

- (instancetype)initWithSuiteName:(NSString *)suiteName {
    return %orig(spoof(suiteName));
}

%end

// ── Keychain access group ─────────────────────────────────────────────────────
// Tailscale's Swift code passes the bundle ID as keychain access group prefix.
// We intercept SecItem* calls by hooking the Security framework wrappers via
// method swizzle on the Objective-C bridge where available.
// For pure C SecItem calls, the dylib is loaded early enough that the
// app group entitlements on the binary already match (handled by patch_ipa.py).

// ── CFBundle (CoreFoundation level) ──────────────────────────────────────────

static IMP orig_CFBundleGetIdentifier = NULL;

static CFStringRef replaced_CFBundleGetIdentifier(CFBundleRef bundle) {
    CFStringRef orig = ((CFStringRef(*)(CFBundleRef))orig_CFBundleGetIdentifier)(bundle);
    if (!orig) return orig;
    NSString *ns = (__bridge NSString *)orig;
    NSString *spoofed = spoof(ns);
    return (__bridge CFStringRef)spoofed;
}

%ctor {
    // Swizzle CFBundleGetIdentifier at the C level
    void *cf = dlopen("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", RTLD_NOW);
    if (cf) {
        void *sym = dlsym(cf, "CFBundleGetIdentifier");
        if (sym) {
            // Use MSHookFunction from MobileSubstrate (available via Theos)
            MSHookFunction(sym, (void *)replaced_CFBundleGetIdentifier, (void **)&orig_CFBundleGetIdentifier);
        }
    }
}
