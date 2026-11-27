//! A speech engine registered without allocating weights until its first decode.
//! The caller's existing engine mutex serializes resolution and all subsequent use.
pub struct SpeechModel<T> {
    value: Option<Result<T, String>>,
    loader: Option<Box<dyn FnOnce() -> Result<T, String> + Send>>,
}

impl<T> SpeechModel<T> {
    pub fn deferred(loader: impl FnOnce() -> Result<T, String> + Send + 'static) -> Self {
        Self {
            value: None,
            loader: Some(Box::new(loader)),
        }
    }

    pub fn loaded(value: T) -> Self {
        Self {
            value: Some(Ok(value)),
            loader: None,
        }
    }

    pub fn is_loaded(&self) -> bool {
        matches!(self.value, Some(Ok(_)))
    }

    pub fn error(&self) -> Option<&str> {
        self.value
            .as_ref()
            .and_then(|value| value.as_ref().err().map(String::as_str))
    }

    pub fn get_or_load(&mut self) -> Result<&mut T, String> {
        let loader = &mut self.loader;
        self.value
            .get_or_insert_with(|| loader.take().expect("unresolved speech model has a loader")())
            .as_mut()
            .map_err(|error| error.clone())
    }
}

#[cfg(test)]
mod tests {
    use super::SpeechModel;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc, Mutex,
    };

    #[test]
    fn registering_or_dropping_an_unused_model_does_not_load_weights() {
        let calls = Arc::new(AtomicUsize::new(0));
        let count = calls.clone();
        let model = SpeechModel::deferred(move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(42)
        });
        assert!(!model.is_loaded());
        assert!(model.error().is_none());
        drop(model);
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn first_decode_loads_once_and_later_decodes_reuse_the_same_model() {
        let calls = Arc::new(AtomicUsize::new(0));
        let count = calls.clone();
        let mut model = SpeechModel::deferred(move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(vec![1])
        });
        model.get_or_load().unwrap().push(2);
        assert_eq!(model.get_or_load().unwrap(), &[1, 2]);
        assert!(model.is_loaded());
        assert!(model.error().is_none());
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn concurrent_coach_and_dictation_requests_share_one_initialization() {
        let calls = Arc::new(AtomicUsize::new(0));
        let count = calls.clone();
        let model = Arc::new(Mutex::new(SpeechModel::deferred(move || {
            count.fetch_add(1, Ordering::SeqCst);
            Ok(42)
        })));
        let barrier = Arc::new(std::sync::Barrier::new(8));
        let handles: Vec<_> = (0..8)
            .map(|_| {
                let model = model.clone();
                let barrier = barrier.clone();
                std::thread::spawn(move || {
                    barrier.wait();
                    assert_eq!(*model.lock().unwrap().get_or_load().unwrap(), 42);
                })
            })
            .collect();
        for handle in handles {
            handle.join().unwrap();
        }
        assert_eq!(calls.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn failures_are_retained_without_automatic_retry_and_explicit_setup_can_replace_them() {
        let calls = Arc::new(AtomicUsize::new(0));
        let count = calls.clone();
        let mut model = SpeechModel::<u8>::deferred(move || {
            count.fetch_add(1, Ordering::SeqCst);
            Err("Cached model is unavailable".into())
        });
        for _ in 0..3 {
            assert_eq!(
                model.get_or_load().unwrap_err(),
                "Cached model is unavailable"
            );
        }
        assert!(!model.is_loaded());
        assert_eq!(model.error(), Some("Cached model is unavailable"));
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        model = SpeechModel::loaded(7);
        assert!(model.is_loaded());
        assert!(model.error().is_none());
        assert_eq!(*model.get_or_load().unwrap(), 7);
    }
}
