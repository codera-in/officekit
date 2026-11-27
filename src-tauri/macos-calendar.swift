import Foundation
import EventKit

// All EventKit reads run on a serial background queue; permission UI never waits
// on a Rust scheduler lock or blocks the main queue.
private let calendarQueue = DispatchQueue(label: "app.officekit.calendar")
private let calendarStore = EKEventStore()
private var calendarRequestPending = false

@_cdecl("officekit_calendar_request_access")
func officekitCalendarRequestAccess() {
    calendarQueue.async {
        guard EKEventStore.authorizationStatus(for: .event) == .notDetermined,
              !calendarRequestPending else { return }
        calendarRequestPending = true
        DispatchQueue.main.async {
            calendarStore.requestFullAccessToEvents { _, _ in
                calendarQueue.async { calendarRequestPending = false }
            }
        }
    }
}

@_cdecl("officekit_calendar_snapshot")
func officekitCalendarSnapshot(_ enabled: Bool) -> UnsafeMutablePointer<CChar>? {
    let value: [String: Any] = calendarQueue.sync {
        let access = EKEventStore.authorizationStatus(for: .event)
        let status: String
        switch access {
        case .fullAccess: status = "allowed"
        case .notDetermined: status = calendarRequestPending ? "requesting" : "permission-needed"
        case .denied, .writeOnly: status = "denied"
        case .restricted: status = "restricted"
        default: status = "error"
        }
        guard enabled && status == "allowed" else {
            return ["status": status, "calendars": [], "events": []]
        }
        // Refetch after edits, account changes, or waking; never read Calendar's private DB.
        calendarStore.refreshSourcesIfNecessary()
        let calendars = calendarStore.calendars(for: .event)
        guard calendars.count <= 256 else { return ["status": "error", "calendars": [], "events": []] }
        let now = Date()
        let predicate = calendarStore.predicateForEvents(withStart: now.addingTimeInterval(-10), end: now.addingTimeInterval(1800), calendars: calendars)
        let events = calendarStore.events(matching: predicate).filter { event in
            !event.isAllDay && event.status != .canceled
                && !(event.attendees ?? []).contains(where: { $0.isCurrentUser && $0.participantStatus == .declined })
                && event.startDate >= now.addingTimeInterval(-8)
                && event.startDate <= now.addingTimeInterval(1800)
        }.sorted { $0.startDate < $1.startDate }
        guard events.count <= 2048 else { return ["status": "error", "calendars": [], "events": []] }
        let rows: [[String: Any]] = events.compactMap { event in
            guard let identifier = event.eventIdentifier, let calendar = event.calendar else { return nil }
            let start = event.startDate.timeIntervalSince1970
            guard start.isFinite && start >= 0 else { return nil }
            let occurrence = (event.occurrenceDate ?? event.startDate).timeIntervalSince1970
            return ["id": "\(identifier)|\(Int64(occurrence))", "calendarId": calendar.calendarIdentifier,
                    "title": String((event.title ?? "Untitled meeting").prefix(512)),
                    "calendarTitle": String(calendar.title.prefix(512)), "start": UInt64(start)]
        }
        return ["status": "allowed", "calendars": calendars.map { ["id": $0.calendarIdentifier, "title": String($0.title.prefix(512))] }, "events": rows]
    }
    guard let data = try? JSONSerialization.data(withJSONObject: value), let json = String(data: data, encoding: .utf8) else { return nil }
    return strdup(json)
}

@_cdecl("officekit_calendar_free")
func officekitCalendarFree(_ pointer: UnsafeMutablePointer<CChar>?) { free(pointer) }
