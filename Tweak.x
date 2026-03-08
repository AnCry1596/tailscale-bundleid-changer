#import <Foundation/Foundation.h>
#import <substrate.h>

static NSString *const kFakeBundleID = @"annnekkk.modified.tailscale";
static NSString *const kRealBundleID = @"io.tailscale.ipn.ios";

static NSString *spoof(NSString *s) {
    if (!s) return s;
    if ([s isEqualToString:kFakeBundleID]) return kRealBundleID;
    if ([s hasPrefix:[kFakeBundleID stringByAppendingString:@"."]]) {
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
    return [info copy];
}

- (id)objectForInfoDictionaryKey:(NSString *)key {
    id val = %orig;
    if ([val isKindOfClass:[NSString class]] &&
        [@[@"CFBundleIdentifier", @"WKAppBundleIdentifier"] containsObject:key])
        return spoof(val);
    return val;
}

// Hook the underlying plist dictionary directly
- (id)objectForKey:(NSString *)key inTable:(NSString *)table {
    id val = %orig;
    if ([key isEqualToString:@"CFBundleIdentifier"] && [val isKindOfClass:[NSString class]])
        return spoof(val);
    return val;
}

%end

// ── NSUserDefaults (App Groups) ───────────────────────────────────────────────

%hook NSUserDefaults

- (instancetype)initWithSuiteName:(NSString *)suiteName {
    return %orig(spoof(suiteName));
}

%end

// ── CFBundleGetIdentifier (CoreFoundation C function) ─────────────────────────

static CFStringRef (*orig_CFBundleGetIdentifier)(CFBundleRef bundle);

static CFStringRef replaced_CFBundleGetIdentifier(CFBundleRef bundle) {
    CFStringRef orig = orig_CFBundleGetIdentifier(bundle);
    if (!orig) return orig;
    NSString *spoofed = spoof((__bridge NSString *)orig);
    return (__bridge CFStringRef)spoofed;
}

// ── Early init via __attribute__((constructor)) ───────────────────────────────
// This runs before %ctor (which runs at +load time) ensuring CFBundle
// is hooked as early as possible — before any Swift static initializers fire.

__attribute__((constructor))
static void earlyInit(void) {
    MSHookFunction(
        (void *)CFBundleGetIdentifier,
        (void *)replaced_CFBundleGetIdentifier,
        (void **)&orig_CFBundleGetIdentifier
    );
}

%ctor {
    // %ctor runs after earlyInit; NSBundle hooks are registered automatically
    // by the Logos %hook machinery at dylib load time, nothing extra needed here.
}
