#import "macos-audio-tap.h"

BOOL OfficeKitInstallAudioTap(AVAudioNode *node, AVAudioFormat *format, AVAudioNodeTapBlock block) {
    @try {
#if __MAC_OS_X_VERSION_MAX_ALLOWED >= 270000
        if (@available(macOS 27.0, *)) {
            NSError *error = nil;
            BOOL installed = [node installTapOnBus:0 bufferSize:1024 format:format error:&error block:block];
            if (!installed) NSLog(@"OfficeKit audio tap failed: %@", error.localizedDescription);
            return installed;
        }
#endif
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        [node installTapOnBus:0 bufferSize:1024 format:format block:block];
#pragma clang diagnostic pop
        return YES;
    } @catch (NSException *exception) {
        // AVFAudio can raise Objective-C exceptions that Swift do/catch cannot catch.
        NSLog(@"OfficeKit audio tap rejected: %@", exception.reason);
        return NO;
    }
}
