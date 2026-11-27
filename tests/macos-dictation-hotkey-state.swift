import Foundation
import AVFoundation
import CoreAudio
import AppKit

func captureLifecycleLockSerializesCompetingCallers() -> Bool {
    let lifecycleLock = DictationCaptureLifecycleLock()
    let stateLock = NSLock()
    let firstEntered = DispatchSemaphore(value: 0)
    let contenderAtLock = DispatchSemaphore(value: 0)
    let contenderEntered = DispatchSemaphore(value: 0)
    let releaseFirst = DispatchSemaphore(value: 0)
    let group = DispatchGroup()
    var activeCallers = 0
    var maximumCallers = 0
    var engineExists = false
    var engineConstructions = 0

    group.enter()
    DispatchQueue.global().async {
        lifecycleLock.withLock {
            stateLock.lock()
            activeCallers += 1
            maximumCallers = max(maximumCallers, activeCallers)
            if !engineExists {
                engineExists = true
                engineConstructions += 1
            }
            stateLock.unlock()
            firstEntered.signal()
            _ = releaseFirst.wait(timeout: .now() + 2)
            stateLock.lock()
            activeCallers -= 1
            stateLock.unlock()
        }
        group.leave()
    }

    guard firstEntered.wait(timeout: .now() + 2) == .success else {
        releaseFirst.signal()
        _ = group.wait(timeout: .now() + 2)
        return false
    }

    group.enter()
    DispatchQueue.global().async {
        contenderAtLock.signal()
        lifecycleLock.withLock {
            stateLock.lock()
            activeCallers += 1
            maximumCallers = max(maximumCallers, activeCallers)
            if !engineExists {
                engineExists = true
                engineConstructions += 1
            }
            stateLock.unlock()
            contenderEntered.signal()
            stateLock.lock()
            activeCallers -= 1
            stateLock.unlock()
        }
        group.leave()
    }

    guard contenderAtLock.wait(timeout: .now() + 2) == .success else {
        releaseFirst.signal()
        _ = group.wait(timeout: .now() + 2)
        return false
    }
    let enteredBeforeRelease = contenderEntered.wait(timeout: .now() + 0.1) == .success
    releaseFirst.signal()
    let enteredAfterRelease = enteredBeforeRelease || contenderEntered.wait(timeout: .now() + 2) == .success
    let callsFinished = group.wait(timeout: .now() + 2) == .success
    stateLock.lock()
    let oneEngine = engineConstructions == 1
    let serialized = maximumCallers == 1
    stateLock.unlock()
    return !enteredBeforeRelease && enteredAfterRelease && callsFinished && oneEngine && serialized
}

@main
struct MacOSDictationHotkeyStateTests {
    static func main() {
        require(dictationPasteTargetMatches(expectedPID: 42, currentPID: 42), "Paste may target the captured app")
        require(!dictationPasteTargetMatches(expectedPID: 42, currentPID: 43), "An app switch must suppress paste")
        require(!dictationPasteTargetMatches(expectedPID: 42, currentPID: nil), "Missing foreground target must suppress paste")
        require(dictationPasteTargetMatches(expectedPID: nil, currentPID: 43), "Explicit manual paste targets the current app")
        require(screenshotShortcutMatches(keyCode: 22, flags: [.command, .shift], isRepeat: false, choice: 1), "Command Shift 6 must trigger capture")
        require(screenshotShortcutMatches(keyCode: 1, flags: [.control, .shift], isRepeat: false, choice: 2), "Control Shift S must trigger capture")
        require(!screenshotShortcutMatches(keyCode: 22, flags: [.command], isRepeat: false, choice: 1), "Incomplete shortcut must not capture")
        require(!screenshotShortcutMatches(keyCode: 22, flags: [.command, .shift, .option], isRepeat: false, choice: 1), "Extra modifiers must not capture")
        require(!screenshotShortcutMatches(keyCode: 22, flags: [.command, .shift], isRepeat: true, choice: 1), "Held shortcut must not repeat capture")
        require(!screenshotShortcutMatches(keyCode: 22, flags: [.command, .shift], isRepeat: false, choice: 0), "Disabled shortcut must not capture")
        let first = officekitDictationOverlayBegin()
        require(officekitDictationOverlayValid(first) == 1, "New recording must be active")
        officekitDictationOverlayCancel()
        require(officekitDictationOverlayValid(first) == 0, "Escape must invalidate the recording")
        let second = officekitDictationOverlayBegin()
        require(second != first && officekitDictationOverlayValid(first) == 0, "New recording must never authorize an old result")
        officekitDictationOverlayProcessing(second)
        officekitDictationOverlayCancel()
        require(officekitDictationOverlayValid(second) == 0, "Cancellation during processing must suppress paste")
        let third = officekitDictationOverlayBegin()
        officekitDictationOverlayFinish(second)
        require(officekitDictationOverlayValid(third) == 1, "Old completion must not dismiss a new session")
        officekitDictationOverlayFinish(third)
        require(officekitDictationOverlayValid(third) == 0, "Finished sessions must reject another paste")
        require(!dictationAudioInputDeviceIsUsable(status: noErr, device: kAudioObjectUnknown), "No default microphone must be rejected before constructing an audio engine")
        require(!dictationAudioInputDeviceIsUsable(status: -1, device: 72), "A failed hardware lookup must not claim a usable microphone")
        require(dictationAudioInputDeviceIsUsable(status: noErr, device: 72), "A successfully discovered input may start capture")
        require(!dictationCoachWindowShouldDrain(sampleCount: 159_999, minimum: 160_000, maximum: 240_000, capacity: 240_000, coachActive: true, dictationActive: false), "Coach analysis waits for a full ten-second window")
        require(dictationCoachWindowShouldDrain(sampleCount: 160_000, minimum: 160_000, maximum: 240_000, capacity: 240_000, coachActive: true, dictationActive: false), "A bounded speech window is eligible for local recognition")
        require(!dictationCoachWindowShouldDrain(sampleCount: 160_000, minimum: 160_000, maximum: 240_000, capacity: 240_000, coachActive: true, dictationActive: true), "Standalone coach analysis yields while STT owns capture")
        require(!dictationCoachWindowShouldDrain(sampleCount: 240_001, minimum: 160_000, maximum: 240_000, capacity: 250_000, coachActive: true, dictationActive: false), "Oversized coach audio is never drained to recognition")
        require(!dictationCoachWindowShouldDrain(sampleCount: 200_000, minimum: 160_000, maximum: 240_000, capacity: 180_000, coachActive: true, dictationActive: false), "Native copy never exceeds the Rust destination buffer")
        require(dictationCoachShouldKeepDictationGeneration(active: true, dictationVisible: true, cancelled: false), "Enabling Speech Coach during STT preserves its active overlay generation")
        require(!dictationCoachShouldKeepDictationGeneration(active: true, dictationVisible: true, cancelled: true), "A cancelled STT session cannot be revived by enabling Speech Coach")
        var startGate = DictationCaptureStartGate()
        var tapInstallations = 0
        require(startGate.begin(), "The first capture owner reserves shared engine construction")
        tapInstallations += 1
        require(!startGate.begin(), "An overlapping coach or dictation start cannot construct a second engine")
        require(tapInstallations == 1, "Concurrent coach and dictation starts share one engine and input tap")
        startGate.finish()
        require(!startGate.isStarting, "The construction gate releases after the shared engine starts")
        let lifecycleLock = DictationCaptureLifecycleLock()
        var nestedLifecycleCompleted = false
        lifecycleLock.withLock {
            lifecycleLock.withLock { nestedLifecycleCompleted = true }
        }
        require(nestedLifecycleCompleted, "Coach start can safely call the shared start operation under the lifecycle lock")
        require(captureLifecycleLockSerializesCompetingCallers(), "Competing coach and dictation lifecycle callers serialize around shared engine construction")
        require(dictationCaptureHasActiveOwner(coachActive: true, dictationActive: true), "Stopping one capture owner keeps the shared engine for the other")
        require(dictationCaptureHasActiveOwner(coachActive: false, dictationActive: true), "Stopping coaching leaves active dictation capture running")
        require(!dictationCaptureHasActiveOwner(coachActive: false, dictationActive: false), "The shared engine can stop after its final owner releases it")
        require(dictationCoachCanAttach(engineRunning: true, dictationActive: true, coachActive: false), "Coaching can join a dictation that is already recording")
        require(!dictationCoachCanAttach(engineRunning: false, dictationActive: true, coachActive: false), "Coaching never opens the microphone by itself")
        require(!dictationCoachCanAttach(engineRunning: true, dictationActive: false, coachActive: false), "Coaching does not attach when no dictation is recording")
        require(!dictationCoachCanAttach(engineRunning: true, dictationActive: true, coachActive: true), "A coach already listening keeps its own ownership")
        let attachedRelease = dictationCoachOwnershipAfterDictationStops(coachActive: true, attachedByDictation: true)
        require(!attachedRelease.coachActive && !attachedRelease.attachedByDictation && attachedRelease.releasedAttachedCoach, "Coaching that joined a dictation leaves with it so the microphone is released")
        let soloKeeps = dictationCoachOwnershipAfterDictationStops(coachActive: true, attachedByDictation: false)
        require(soloKeeps.coachActive && !soloKeeps.releasedAttachedCoach, "A Listen In session keeps running after a dictation ends")
        let neither = dictationCoachOwnershipAfterDictationStops(coachActive: false, attachedByDictation: false)
        require(!neither.coachActive && !neither.releasedAttachedCoach, "Nothing changes when the coach was not involved")
        let zone = dictationCoachZoneGeometry(pace: 120, targetMin: 110, targetMax: 160, trackWidth: 190)
        require(zone != nil && abs(zone!.markerX - 63.3333) < 0.01 && abs(zone!.targetWidth - 52.7777) < 0.01, "The pace marker and target zone use the same WPM scale")
        let cappedZone = dictationCoachZoneGeometry(pace: 300, targetMin: 110, targetMax: 160, trackWidth: 190)
        require(cappedZone != nil && cappedZone!.markerX == 190, "Out-of-range pace remains visibly beyond the target and is bounded to the track")
        require(dictationCoachMeasuringText(speechSeconds: 0) == "Measuring your pace · 0 of 10 s of speech", "A silent coach shows zero measured seconds")
        require(dictationCoachMeasuringText(speechSeconds: 4.9) == "Measuring your pace · 4 of 10 s of speech", "Measured seconds count whole seconds of speech")
        require(dictationCoachMeasuringText(speechSeconds: 10) == nil, "The measuring line ends once a pace reading is possible")
        require(dictationCoachMeasuringText(speechSeconds: .nan) == "Measuring your pace · 0 of 10 s of speech" && dictationCoachMeasuringText(speechSeconds: -3) == "Measuring your pace · 0 of 10 s of speech", "Invalid speech seconds never produce a bad count")
        require(dictationCoachLevelBarHeights(rms: 0) == [2, 2, 2, 2, 2], "Silence leaves the level bars flat")
        let loud = dictationCoachLevelBarHeights(rms: 1)
        require(loud.count == 5 && loud.max() == 14 && loud.min()! >= 2 && loud[2] == 14, "Loud speech peaks in the middle bar and stays inside the panel")
        let talking = dictationCoachLevelBarHeights(rms: 0.03)
        require(talking[2] >= 10 && talking[2] <= 14 && talking[0] < talking[2], "Normal speaking volume lifts the middle bar clearly above the flat baseline")
        let quiet = dictationCoachLevelBarHeights(rms: 0.003)
        require(quiet[2] >= 4 && quiet[2] < talking[2], "Quiet speech still moves the bars, less than normal speech")
        require(dictationCoachLevelBarHeights(rms: .nan) == [2, 2, 2, 2, 2] && dictationCoachLevelBarHeights(rms: -1) == [2, 2, 2, 2, 2], "Invalid levels keep the bars flat")
        let coachOnly = dictationOverlayChrome(coachEnabled: true, dictationVisible: false)
        require(coachOnly.levelBars && !coachOnly.legacyMeter && !coachOnly.legacyEscHint && !coachOnly.legacyMicrophone, "Coach-only mode hides the dictation controls that overlap the coach rows and shows no Esc hint (Esc cannot stop the coach)")
        let both = dictationOverlayChrome(coachEnabled: true, dictationVisible: true)
        require(coachOnly.closeButton, "The Listen In panel has a close button")
        require(!both.closeButton && !dictationOverlayChrome(coachEnabled: false, dictationVisible: true).closeButton && !dictationOverlayChrome(coachEnabled: false, dictationVisible: false).closeButton, "Dictation, dictation with coaching and a hidden panel never show the coach close button")
        require(dictationCoachLevelBarsOriginX(closeButtonVisible: true) < dictationCoachLevelBarsOriginX(closeButtonVisible: false), "The level bars move left to make room for the close button")
        require(dictationCoachLevelBarsOriginX(closeButtonVisible: true) + 24 + 4 <= 328, "The level bars end before the close button starts")
        require(!both.levelBars && !both.legacyMeter && both.legacyEscHint && !both.legacyMicrophone && both.cancelInCorner, "Dictation with coaching drops the meter and microphone that sat on the pace row, and moves Stop and Esc to the corner")
        require(!coachOnly.cancelInCorner && !dictationOverlayChrome(coachEnabled: false, dictationVisible: true).cancelInCorner, "Only dictation with coaching uses the corner")
        let corner = dictationCancelLayout(inCorner: true)
        let coachRows = CGRect(x: 16, y: 13, width: 336, height: 49)
        require(!corner.cancel.intersects(coachRows) && !corner.escHint.intersects(coachRows), "Stop and Esc in the corner stay clear of the pitch, pace and WPM rows")
        require(!corner.cancel.intersects(corner.escHint) && corner.escHint.maxX <= corner.cancel.minX && 16 + corner.titleWidth <= corner.escHint.minX, "Stop, Esc and the title text do not overlap each other")
        require(corner.cancel.maxX <= 360 && corner.cancel.maxY <= 116, "The corner Stop button stays inside the 360 x 116 panel")
        let dictationOnly = dictationOverlayChrome(coachEnabled: false, dictationVisible: true)
        require(!dictationOnly.levelBars && dictationOnly.legacyMeter, "Plain dictation is unchanged")
        require(dictationModifierKeyIsDown(keyCode: 60, flags: 131332), "Recorded Right Shift down event must start recording even when CGEventSource reports false")
        require(!dictationModifierKeyIsDown(keyCode: 60, flags: 256), "Recorded Right Shift release must stop recording")
        require(!dictationModifierKeyIsDown(keyCode: 60, flags: 0x20002), "Left Shift must not activate Right Shift")
        require(dictationModifierKeyIsDown(keyCode: 60, flags: 0x20006), "Right Shift remains pressed while both Shift keys are held")
        require(!dictationModifierKeyIsDown(keyCode: 60, flags: 0x20002), "Right Shift release must stop even if Left Shift remains down")
        require(OfficeKitAudioTapTestResult(0), "Successful tap installation must remain successful")
        require(!OfficeKitAudioTapTestResult(1), "Tap setup NSError must be a recoverable failure")
        require(!OfficeKitAudioTapTestResult(2), "AVFAudio Objective-C exception must not abort OfficeKit")
        require(dictationMicrophonePermissionCode(for: .authorized) == 0, "Authorized media capture must allow access")
        require(dictationMicrophonePermissionCode(for: .notDetermined) == 1, "Undetermined media capture must remain requestable")
        require(dictationMicrophonePermissionCode(for: .denied) == 2, "Denied media capture must remain denied")
        require(dictationMicrophonePermissionCode(for: .restricted) == 3, "Restricted media capture must remain unavailable")
        require(dictationShouldRequestMicrophoneAccess(for: .notDetermined), "An undetermined permission must call macOS directly, without a discovered device")
        require(!dictationShouldRequestMicrophoneAccess(for: .authorized), "Do not request permission after it has been granted")
        require(!dictationShouldRequestMicrophoneAccess(for: .denied), "A denied permission must be changed in System Settings")

        require(dictationNativeKeyCode(for: 0) == 63, "Fn must map to macOS virtual key code 63")
        require(
            [Int32(1), 2, 3, 4, 5, 6, 7, 8].compactMap({ dictationNativeKeyCode(for: $0) }) == [58, 61, 59, 62, 55, 54, 56, 60],
            "Every physical modifier selection must map to its macOS virtual key code"
        )
        require(dictationNativeKeyCode(for: 9) == nil, "Custom chords use their recorded key code")

        var state = DictationModifierKeyState()
        state.update(eventKeyCode: 58, selectedKeyCode: 58, keyIsDown: true)
        require(state.isPressed, "Selected left Option press must begin dictation")

        // Releasing right Option must not keep left Option logically pressed.
        state.update(eventKeyCode: 61, selectedKeyCode: 58, keyIsDown: false)
        require(state.isPressed, "An unrelated right Option event must not alter left Option state")

        // The flagsChanged event for left Option reports aggregate Option state,
        // which may remain set because right Option is still physically down.
        state.update(eventKeyCode: 58, selectedKeyCode: 58, keyIsDown: false)
        require(!state.isPressed, "Releasing the selected physical key must stop dictation")

        state.update(eventKeyCode: 58, selectedKeyCode: 58, keyIsDown: true)
        state.reset()
        require(!state.isPressed, "Reset must clear held-key state")
        print("macOS dictation, screenshot shortcut, cancellation and audio exception state: 72 checks passed")
    }

    private static func require(_ condition: @autoclosure () -> Bool, _ message: String) {
        guard condition() else { fatalError(message) }
    }
}
