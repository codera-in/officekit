use serde::Serialize;
#[cfg(target_os = "macos")]
use std::ffi::{c_char, c_void, CStr};

#[derive(Debug, Serialize)]
pub struct SystemSensorMetric {
    name: String,
    current_c: f64,
    high_c: Option<f64>,
}

fn valid_sensor(name: &str, current_c: f64) -> Option<SystemSensorMetric> {
    let name = name.trim();
    if name.is_empty()
        || name.len() > 60
        || name.chars().any(char::is_control)
        || !current_c.is_finite()
        || !(0.0..=150.0).contains(&current_c)
    {
        return None;
    }
    Some(SystemSensorMetric {
        name: name.to_owned(),
        current_c: (current_c * 10.0).round() / 10.0,
        high_c: None,
    })
}

#[cfg(target_os = "macos")]
unsafe extern "C" {
    fn officekit_macos_sensor_read(
        callback: extern "C" fn(*mut c_void, *const c_char, f64),
        context: *mut c_void,
    ) -> i32;
}

#[cfg(target_os = "macos")]
extern "C" fn collect_sensor(context: *mut c_void, name: *const c_char, current_c: f64) {
    if context.is_null() || name.is_null() {
        return;
    }
    let readings = unsafe { &mut *(context.cast::<Vec<SystemSensorMetric>>()) };
    if readings.len() >= 16 {
        return;
    }
    let Ok(name) = unsafe { CStr::from_ptr(name) }.to_str() else {
        return;
    };
    let Some(reading) = valid_sensor(name, current_c) else {
        return;
    };
    if !readings
        .iter()
        .any(|existing| existing.name == reading.name)
    {
        readings.push(reading);
    }
}

#[tauri::command]
pub fn system_sensor_metrics() -> Option<Vec<SystemSensorMetric>> {
    #[cfg(target_os = "macos")]
    {
        let mut readings = Vec::with_capacity(16);
        let result = unsafe {
            officekit_macos_sensor_read(
                collect_sensor,
                (&mut readings as *mut Vec<SystemSensorMetric>).cast(),
            )
        };
        if result > 0 && !readings.is_empty() {
            return Some(readings);
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::valid_sensor;

    #[test]
    fn sensor_values_are_finite_bounded_and_named() {
        let reading = valid_sensor(" CPU Package ", 58.56).unwrap();
        assert_eq!(reading.name, "CPU Package");
        assert_eq!(reading.current_c, 58.6);
        assert_eq!(reading.high_c, None);
        assert!(valid_sensor("", 40.0).is_none());
        assert!(valid_sensor("bad\nname", 40.0).is_none());
        assert!(valid_sensor(&"n".repeat(61), 40.0).is_none());
        assert!(valid_sensor("CPU", f64::NAN).is_none());
        assert!(valid_sensor("CPU", -1.0).is_none());
        assert!(valid_sensor("CPU", 151.0).is_none());
    }
}
