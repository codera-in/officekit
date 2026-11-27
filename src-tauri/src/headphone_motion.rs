use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Mutex, OnceLock};

static ENABLED: AtomicBool = AtomicBool::new(false);

#[derive(Clone, Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MotionSnapshot {
    pub status: String,
    pub calibrated: bool,
    pub relative_pitch_degrees: Option<f64>,
    pub relative_roll_degrees: Option<f64>,
    pub stable: bool,
}

#[derive(Clone, Copy, Default)]
struct RawMotion {
    status: i32,
    pitch: f64,
    roll: f64,
    speed: f64,
    timestamp: f64,
    now: f64,
    generation: u64,
}

#[derive(Default)]
struct Policy {
    baseline: Option<(f64, f64)>,
    candidate: Option<(f64, f64, f64)>,
    last_timestamp: Option<f64>,
    generation: Option<u64>,
}

fn delta(value: f64, baseline: f64) -> f64 {
    (value - baseline + std::f64::consts::PI).rem_euclid(std::f64::consts::TAU)
        - std::f64::consts::PI
}

impl Policy {
    fn update(&mut self, raw: RawMotion) -> MotionSnapshot {
        let mut status = match raw.status {
            0 => "disabled",
            1 => "permission-needed",
            2 => "denied",
            3 => "unavailable",
            4 => "calibrating",
            6 => "disconnected",
            _ => "error",
        };
        if raw.status == 4 {
            let valid = [raw.pitch, raw.roll, raw.speed, raw.timestamp, raw.now]
                .iter()
                .all(|v| v.is_finite())
                && raw.pitch.abs() <= std::f64::consts::PI
                && raw.roll.abs() <= std::f64::consts::PI
                && raw.speed >= 0.0
                && raw.timestamp > 0.0;
            if !valid {
                status = "error";
            } else if raw.now < raw.timestamp
                || raw.now - raw.timestamp > 2.0
                || self.last_timestamp.is_some_and(|last| raw.timestamp < last)
            {
                status = "stale";
            }
        }
        if status != "calibrating" {
            *self = Self::default();
            return MotionSnapshot {
                status: status.into(),
                calibrated: false,
                relative_pitch_degrees: None,
                relative_roll_degrees: None,
                stable: false,
            };
        }
        let gap = self
            .last_timestamp
            .is_some_and(|last| raw.timestamp - last > 2.0)
            || self
                .generation
                .is_some_and(|generation| generation != raw.generation);
        if gap {
            self.baseline = None;
            self.candidate = None;
        }
        let stable = raw.speed <= 0.15;
        if !stable {
            self.candidate = None;
        }
        if self.baseline.is_none() && stable {
            let restart = self.candidate.is_none_or(|(_, pitch, roll)| {
                delta(raw.pitch, pitch).abs() > 3.0_f64.to_radians()
                    || delta(raw.roll, roll).abs() > 3.0_f64.to_radians()
            });
            if restart {
                self.candidate = Some((raw.timestamp, raw.pitch, raw.roll));
            }
            if let Some((start, pitch, roll)) = self.candidate {
                if raw.timestamp - start >= 5.0 {
                    self.baseline = Some((pitch, roll));
                }
            }
        }
        self.last_timestamp = Some(raw.timestamp);
        self.generation = Some(raw.generation);
        MotionSnapshot {
            status: if self.baseline.is_some() {
                "ready"
            } else {
                "calibrating"
            }
            .into(),
            calibrated: self.baseline.is_some(),
            relative_pitch_degrees: self
                .baseline
                .map(|(pitch, _)| delta(raw.pitch, pitch).to_degrees()),
            relative_roll_degrees: self
                .baseline
                .map(|(_, roll)| delta(raw.roll, roll).to_degrees()),
            stable,
        }
    }
}

fn policy() -> &'static Mutex<Policy> {
    static POLICY: OnceLock<Mutex<Policy>> = OnceLock::new();
    POLICY.get_or_init(|| Mutex::new(Policy::default()))
}

pub fn action(action: &str) -> Result<MotionSnapshot, String> {
    match action {
        "enable" | "disable" | "calibrate" => {}
        _ => return Err("Unknown headphone motion action".into()),
    }
    if action != "calibrate" {
        ENABLED.store(action == "enable", Ordering::SeqCst);
    }
    // Native dispatch never happens with the policy mutex held.
    native::action(action);
    *policy().lock().unwrap_or_else(|error| error.into_inner()) = Policy::default();
    Ok(snapshot())
}

pub fn snapshot() -> MotionSnapshot {
    let raw = if ENABLED.load(Ordering::SeqCst) {
        native::snapshot()
    } else {
        RawMotion::default()
    };
    policy()
        .lock()
        .unwrap_or_else(|error| error.into_inner())
        .update(raw)
}

// Touching the sensor, even to stop it, makes macOS ask for Motion & Fitness access.
fn should_disable_native_on_shutdown() -> bool {
    ENABLED.load(Ordering::SeqCst)
}

pub fn shutdown() {
    if should_disable_native_on_shutdown() {
        let _ = action("disable");
    }
}

#[cfg(all(target_os = "macos", not(test)))]
mod native {
    use super::RawMotion;
    unsafe extern "C" {
        fn officekit_headphone_motion_action(action: i32);
        fn officekit_headphone_motion_snapshot(
            pitch: *mut f64,
            roll: *mut f64,
            speed: *mut f64,
            timestamp: *mut f64,
            now: *mut f64,
            generation: *mut u64,
        ) -> i32;
    }
    pub fn action(action: &str) {
        unsafe {
            officekit_headphone_motion_action(if action == "enable" {
                1
            } else if action == "disable" {
                0
            } else {
                2
            });
        }
    }
    pub fn snapshot() -> RawMotion {
        let mut raw = RawMotion::default();
        raw.status = unsafe {
            officekit_headphone_motion_snapshot(
                &mut raw.pitch,
                &mut raw.roll,
                &mut raw.speed,
                &mut raw.timestamp,
                &mut raw.now,
                &mut raw.generation,
            )
        };
        raw
    }
}

#[cfg(any(not(target_os = "macos"), test))]
mod native {
    use super::RawMotion;
    use std::sync::atomic::{AtomicBool, Ordering};
    static ENABLED: AtomicBool = AtomicBool::new(false);
    pub fn action(action: &str) {
        if action != "calibrate" {
            ENABLED.store(action == "enable", Ordering::SeqCst);
        }
    }
    pub fn snapshot() -> RawMotion {
        RawMotion {
            status: if ENABLED.load(Ordering::SeqCst) { 3 } else { 0 },
            ..RawMotion::default()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Mutex;

    static ENABLED_TEST_LOCK: Mutex<()> = Mutex::new(());

    fn raw(time: f64, pitch: f64) -> RawMotion {
        RawMotion {
            status: 4,
            pitch,
            roll: 0.0,
            speed: 0.0,
            timestamp: time,
            now: time,
            generation: 0,
        }
    }

    #[test]
    fn requires_five_seconds_of_continuous_still_samples() {
        let mut policy = Policy::default();
        for time in 1..=5 {
            assert!(!policy.update(raw(time as f64, 0.2)).calibrated);
        }
        let ready = policy.update(raw(6.0, 0.2));
        assert_eq!(ready.status, "ready");
        assert!(ready.calibrated && ready.stable);
        assert!(ready.relative_pitch_degrees.unwrap().abs() < 1e-9);
        assert!(
            (policy.update(raw(7.0, 0.4)).relative_pitch_degrees.unwrap() - 0.2_f64.to_degrees())
                .abs()
                < 1e-9
        );
    }

    #[test]
    fn stale_disconnect_and_invalid_numbers_never_expose_tilt() {
        for bad in [
            RawMotion {
                status: 6,
                ..raw(1.0, 0.0)
            },
            RawMotion {
                now: 4.0,
                ..raw(1.0, 0.0)
            },
            raw(1.0, f64::NAN),
            raw(1.0, 8.0),
            RawMotion {
                speed: f64::INFINITY,
                ..raw(1.0, 0.0)
            },
            RawMotion {
                now: f64::NAN,
                ..raw(1.0, 0.0)
            },
        ] {
            let mut policy = Policy::default();
            for time in 1..=6 {
                policy.update(raw(time as f64, 0.0));
            }
            let output = policy.update(bad);
            assert!(!output.calibrated && !output.stable);
            assert_eq!(output.relative_pitch_degrees, None);
        }
    }

    #[test]
    fn motion_or_sample_gap_restarts_calibration() {
        let mut policy = Policy::default();
        policy.update(raw(1.0, 0.0));
        policy.update(raw(2.0, 0.0));
        policy.update(raw(3.0, 0.3));
        assert!(!policy.update(raw(7.0, 0.3)).calibrated);
        assert!(!policy.update(raw(8.0, 0.3)).calibrated);
        assert!(
            !policy
                .update(RawMotion {
                    speed: 0.9,
                    ..raw(9.0, 0.3)
                })
                .stable
        );
        assert!(!policy.update(raw(10.0, 0.3)).calibrated);
    }

    #[test]
    fn wrap_around_pitch_and_repeated_samples_are_safe() {
        let mut policy = Policy::default();
        for time in 1..=6 {
            policy.update(raw(time as f64, 3.13));
        }
        let output = policy.update(raw(7.0, -3.13));
        assert!(output.relative_pitch_degrees.unwrap().abs() < 2.0);
        let mut policy = Policy::default();
        for _ in 0..100 {
            assert!(!policy.update(raw(1.0, 0.0)).calibrated);
        }
    }

    #[test]
    fn still_samples_establish_the_baseline_after_five_seconds() {
        let mut policy = Policy::default();
        for time in 1..=6 {
            let result = policy.update(raw(time as f64, 0.0));
            if time == 6 {
                assert!(result.calibrated);
                assert_eq!(result.status, "ready");
            }
        }
    }

    #[test]
    fn a_reconnect_between_polls_invalidates_calibration() {
        let mut policy = Policy::default();
        for time in 1..=6 {
            policy.update(raw(time as f64, 0.0));
        }
        let output = policy.update(RawMotion {
            generation: 1,
            ..raw(7.0, 0.0)
        });
        assert!(!output.calibrated);
    }

    #[test]
    fn quitting_with_sensing_off_never_reaches_the_native_sensor() {
        let _lock = ENABLED_TEST_LOCK
            .lock()
            .expect("enabled test lock is not poisoned");
        assert!(!ENABLED.load(Ordering::SeqCst));
        assert!(!should_disable_native_on_shutdown());
        ENABLED.store(true, Ordering::SeqCst);
        assert!(should_disable_native_on_shutdown());
        ENABLED.store(false, Ordering::SeqCst);
    }

    #[test]
    fn action_validation_and_disabled_stub_do_not_prompt() {
        let _lock = ENABLED_TEST_LOCK
            .lock()
            .expect("enabled test lock is not poisoned");
        assert!(action("unknown").is_err());
        assert_eq!(action("disable").unwrap().status, "disabled");
        assert_eq!(action("enable").unwrap().status, "unavailable");
        assert!(action("calibrate").is_ok());
        shutdown();
        assert_eq!(snapshot().status, "disabled");
    }

    #[test]
    fn every_native_status_fails_closed_and_unknown_codes_are_errors() {
        for (code, expected) in [
            (0, "disabled"),
            (1, "permission-needed"),
            (2, "denied"),
            (3, "unavailable"),
            (5, "error"),
            (6, "disconnected"),
            (99, "error"),
        ] {
            let output = Policy::default().update(RawMotion {
                status: code,
                ..RawMotion::default()
            });
            assert_eq!(output.status, expected);
            assert!(!output.calibrated && !output.stable);
            assert_eq!(output.relative_pitch_degrees, None);
        }
    }

    #[test]
    fn calibration_rejects_every_invalid_or_nonmonotonic_sample() {
        for bad in [
            RawMotion {
                speed: -0.1,
                ..raw(1.0, 0.0)
            },
            RawMotion {
                roll: 4.0,
                ..raw(1.0, 0.0)
            },
            RawMotion {
                timestamp: 0.0,
                ..raw(1.0, 0.0)
            },
            RawMotion {
                now: f64::INFINITY,
                ..raw(1.0, 0.0)
            },
        ] {
            assert_eq!(Policy::default().update(bad).status, "error");
        }
        let mut policy = Policy::default();
        assert_eq!(policy.update(raw(3.0, 0.0)).status, "calibrating");
        assert_eq!(policy.update(raw(2.0, 0.0)).status, "stale");
        assert_eq!(
            policy
                .update(RawMotion {
                    now: 4.0,
                    ..raw(1.0, 0.0)
                })
                .status,
            "stale"
        );
        assert_eq!(
            Policy::default()
                .update(RawMotion {
                    now: 0.0,
                    ..raw(1.0, 0.0)
                })
                .status,
            "stale"
        );
    }
}
