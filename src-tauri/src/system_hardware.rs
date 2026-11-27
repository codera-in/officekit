//! Read-only hardware readings for the System Stats panels: CPU clock speed, power draw, thermal state and fan
//! speeds. The macOS reader returns one small JSON object; this module checks every field against a bound before
//! the web layer sees it, so a misbehaving system interface can never put an impossible number on screen.

use serde::{Deserialize, Serialize};
use serde_json::Value;

const MAX_FANS: usize = 4;

#[derive(Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct CpuFrequency {
    pub efficiency: Option<f64>,
    pub performance: Option<f64>,
    pub all: Option<f64>,
}

#[derive(Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct PowerDraw {
    pub cpu: Option<f64>,
    pub gpu: Option<f64>,
    pub system: Option<f64>,
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
pub struct FanSpeed {
    pub name: String,
    pub rpm: u32,
}

#[derive(Debug, PartialEq, Serialize)]
pub struct HardwareMetrics {
    pub thermal_state: String,
    pub cpu_frequency_mhz: Option<CpuFrequency>,
    pub power_w: Option<PowerDraw>,
    pub fans: Vec<FanSpeed>,
}

fn bounded(value: &Value, low: f64, high: f64, digits: i32) -> Option<f64> {
    let number = value.as_f64()?;
    if !number.is_finite() || number <= low || number >= high {
        return None;
    }
    let scale = 10f64.powi(digits);
    Some((number * scale).round() / scale)
}

/// Parses and bounds the reader's JSON. Anything missing or out of range becomes `None`; a result that is not an
/// object with a known thermal state is rejected as a whole.
pub fn parse_hardware(text: &str) -> Option<HardwareMetrics> {
    if text.len() > 2048 {
        return None;
    }
    let object = serde_json::from_str::<Value>(text).ok()?;
    let object = object.as_object()?;
    let thermal_state = object.get("thermal_state")?.as_str()?;
    if !["nominal", "fair", "serious", "critical"].contains(&thermal_state) {
        return None;
    }
    let cpu_frequency_mhz = object
        .get("cpu_frequency_mhz")
        .and_then(Value::as_object)
        .map(|frequency| CpuFrequency {
            efficiency: frequency
                .get("efficiency")
                .and_then(|v| bounded(v, 0.0, 10_000.0, 0)),
            performance: frequency
                .get("performance")
                .and_then(|v| bounded(v, 0.0, 10_000.0, 0)),
            all: frequency
                .get("all")
                .and_then(|v| bounded(v, 0.0, 10_000.0, 0)),
        });
    let power_w = object
        .get("power_w")
        .and_then(Value::as_object)
        .map(|power| PowerDraw {
            cpu: power.get("cpu").and_then(|v| bounded(v, 0.0, 500.0, 1)),
            gpu: power.get("gpu").and_then(|v| bounded(v, 0.0, 500.0, 1)),
            system: power.get("system").and_then(|v| bounded(v, 0.0, 500.0, 1)),
        });
    let fans = object
        .get("fans")
        .and_then(Value::as_array)
        .map(|list| {
            list.iter()
                .take(16)
                .filter_map(|fan| {
                    let name = fan.get("name")?.as_str()?.trim();
                    let rpm = fan.get("rpm")?.as_u64()?;
                    if name.is_empty()
                        || name.len() > 24
                        || name.chars().any(char::is_control)
                        || rpm > 20_000
                    {
                        return None;
                    }
                    Some(FanSpeed {
                        name: name.to_owned(),
                        rpm: rpm as u32,
                    })
                })
                .take(MAX_FANS)
                .collect()
        })
        .unwrap_or_default();
    Some(HardwareMetrics {
        thermal_state: thermal_state.to_owned(),
        cpu_frequency_mhz: cpu_frequency_mhz
            .filter(|f| f.efficiency.is_some() || f.performance.is_some() || f.all.is_some()),
        power_w: power_w.filter(|p| p.cpu.is_some() || p.gpu.is_some() || p.system.is_some()),
        fans,
    })
}

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_macos_hardware_read(buffer: *mut std::ffi::c_char, capacity: i32) -> i32;
}

/// One reading, or `None` on a Mac that cannot provide it and on every other system.
#[tauri::command]
pub fn system_hardware_metrics() -> Option<HardwareMetrics> {
    #[cfg(target_os = "macos")]
    {
        let mut buffer = vec![0 as std::ffi::c_char; 2048];
        let length =
            unsafe { officekit_macos_hardware_read(buffer.as_mut_ptr(), buffer.len() as i32) };
        if length <= 0 {
            return None;
        }
        let bytes: Vec<u8> = buffer[..length as usize]
            .iter()
            .map(|&byte| byte as u8)
            .collect();
        return parse_hardware(std::str::from_utf8(&bytes).ok()?);
    }
    #[cfg(not(target_os = "macos"))]
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_full_reading_is_parsed_and_rounded() {
        let parsed = parse_hardware(
            r#"{"thermal_state":"fair","cpu_frequency_mhz":{"all":1943.4,"efficiency":1736,"performance":1995},
               "power_w":{"cpu":null,"gpu":0.20000000000000001,"system":29},
               "fans":[{"name":"Left fan","rpm":1330},{"name":"Right fan","rpm":1324}]}"#,
        )
        .unwrap();
        assert_eq!(parsed.thermal_state, "fair");
        assert_eq!(parsed.cpu_frequency_mhz.unwrap().all, Some(1943.0));
        let power = parsed.power_w.unwrap();
        assert_eq!(
            (power.cpu, power.gpu, power.system),
            (None, Some(0.2), Some(29.0))
        );
        assert_eq!(parsed.fans.len(), 2);
        assert_eq!(
            parsed.fans[1],
            FanSpeed {
                name: "Right fan".into(),
                rpm: 1324
            }
        );
    }

    #[test]
    fn missing_sections_are_left_out_instead_of_invented() {
        let parsed = parse_hardware(r#"{"thermal_state":"nominal"}"#).unwrap();
        assert!(
            parsed.cpu_frequency_mhz.is_none()
                && parsed.power_w.is_none()
                && parsed.fans.is_empty()
        );
        let empty = parse_hardware(
            r#"{"thermal_state":"nominal","cpu_frequency_mhz":{"all":null},"power_w":{}}"#,
        )
        .unwrap();
        assert!(empty.cpu_frequency_mhz.is_none() && empty.power_w.is_none());
    }

    #[test]
    fn impossible_numbers_and_odd_fans_are_dropped() {
        let parsed = parse_hardware(
            r#"{"thermal_state":"nominal","cpu_frequency_mhz":{"all":99999,"efficiency":-3,"performance":2000},
               "power_w":{"system":900,"gpu":0},
               "fans":[{"name":"","rpm":10},{"name":"ok","rpm":99999},{"name":"bad\nname","rpm":5},{"name":"Fan 1","rpm":900},
                       {"name":"Fan 2","rpm":901},{"name":"Fan 3","rpm":902},{"name":"Fan 4","rpm":903},{"name":"Fan 5","rpm":904}]}"#,
        )
        .unwrap();
        let frequency = parsed.cpu_frequency_mhz.unwrap();
        assert_eq!(
            (frequency.all, frequency.efficiency, frequency.performance),
            (None, None, Some(2000.0))
        );
        assert!(parsed.power_w.is_none());
        assert_eq!(
            parsed
                .fans
                .iter()
                .map(|fan| fan.name.as_str())
                .collect::<Vec<_>>(),
            ["Fan 1", "Fan 2", "Fan 3", "Fan 4"]
        );
    }

    #[test]
    fn a_bad_result_is_rejected_as_a_whole() {
        assert!(parse_hardware("not json").is_none());
        assert!(parse_hardware("[]").is_none());
        assert!(parse_hardware(r#"{"thermal_state":"on fire"}"#).is_none());
        assert!(parse_hardware(r#"{"cpu_frequency_mhz":{"all":2000}}"#).is_none());
        assert!(parse_hardware(&format!(
            r#"{{"thermal_state":"nominal","pad":"{}"}}"#,
            "x".repeat(3000)
        ))
        .is_none());
    }
}
