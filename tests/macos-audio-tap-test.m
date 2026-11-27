#import "macos-audio-tap-test.h"

// AVAudioNode is a class cluster; a stand-in lets us inject its selector outcomes.
@interface OfficeKitTestAudioNode : NSObject
@property int32_t mode;
@end

@implementation OfficeKitTestAudioNode
- (void)installTapOnBus:(AVAudioNodeBus)bus bufferSize:(AVAudioFrameCount)size format:(AVAudioFormat *)format block:(AVAudioNodeTapBlock)block {
    if (self.mode != 0) [NSException raise:@"OfficeKitTestAudioError" format:@"Simulated format mismatch"];
}
- (BOOL)installTapOnBus:(AVAudioNodeBus)bus bufferSize:(AVAudioFrameCount)size format:(AVAudioFormat *)format error:(NSError **)error block:(AVAudioNodeTapBlock)block {
    if (self.mode == 2) [NSException raise:@"OfficeKitTestAudioError" format:@"Simulated format mismatch"];
    if (self.mode == 1) {
        *error = [NSError errorWithDomain:@"OfficeKitTest" code:1 userInfo:nil];
        return NO;
    }
    return YES;
}
@end

BOOL OfficeKitAudioTapTestResult(int32_t mode) {
    OfficeKitTestAudioNode *node = [[OfficeKitTestAudioNode alloc] init];
    node.mode = mode;
    AVAudioFormat *format = [[AVAudioFormat alloc] initStandardFormatWithSampleRate:16000 channels:1];
    return OfficeKitInstallAudioTap((AVAudioNode *)node, format, ^(AVAudioPCMBuffer *buffer, AVAudioTime *time) {});
}
