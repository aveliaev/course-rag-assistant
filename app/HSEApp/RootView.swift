import SwiftUI

enum AppTab: Int, CaseIterable {
    case schedule, search, assistant, deadlines, profile

    var icon: String {
        switch self {
        case .schedule: "rectangle.grid.1x2.fill"
        case .search: "magnifyingglass"
        case .assistant: "sparkles"
        case .deadlines: "flame.fill"
        case .profile: "person.crop.circle.fill"
        }
    }
}

struct RootView: View {
    @State private var selection: AppTab = .schedule

    init() {
        let initialTab: AppTab = ProcessInfo.processInfo.arguments.contains("--assistant") ? .assistant : .schedule
        _selection = State(initialValue: initialTab)
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            LinearGradient(
                colors: [Color.white, HSETheme.background, Color(red: 0.93, green: 0.95, blue: 0.99)],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()

            if selection == .assistant {
                AssistantView {
                    withAnimation(.snappy(duration: 0.25)) { selection = .schedule }
                }
                .transition(.move(edge: .trailing))
            } else {
                Group {
                    switch selection {
                    case .schedule: ScheduleView()
                    case .search: SearchView()
                    case .deadlines: DeadlinesView()
                    case .profile: ProfileView()
                    case .assistant: EmptyView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .safeAreaPadding(.bottom, 72)

                FloatingTabBar(selection: $selection)
                    .padding(.horizontal, 21)
                    .padding(.bottom, 2)
            }
        }
        .tint(HSETheme.blue)
    }
}

struct HSEBrand: View {
    var body: some View {
        Image("HSEBrand")
            .resizable()
            .scaledToFit()
            .frame(width: 80, height: 35)
            .frame(maxWidth: .infinity)
        .accessibilityLabel("HSE app")
    }
}

private struct FloatingTabBar: View {
    @Binding var selection: AppTab

    var body: some View {
        HStack(spacing: 0) {
            tabButton(.schedule)
            tabButton(.search)
            assistantButton
            tabButton(.deadlines)
            tabButton(.profile)
        }
        .padding(.horizontal, 10)
        .frame(height: 62)
        .background {
            Capsule()
                .fill(Color.white.opacity(0.97))
                .shadow(color: HSETheme.secondary.opacity(0.12), radius: 18, y: 6)
        }
    }

    private func tabButton(_ tab: AppTab) -> some View {
        Button {
            withAnimation(.snappy(duration: 0.25)) { selection = tab }
        } label: {
            Group {
                if tab == .profile {
                    Image("StudentReference")
                        .resizable()
                        .frame(width: 156, height: 339)
                        .offset(x: -122, y: -57)
                        .frame(width: 28, height: 28, alignment: .topLeading)
                        .clipShape(Circle())
                } else {
                    Image(systemName: tab.icon)
                        .font(.system(size: tab == .search ? 27 : 24, weight: .semibold))
                }
            }
                .foregroundStyle(selection == tab ? HSETheme.blue : HSETheme.secondary.opacity(0.72))
                .frame(maxWidth: .infinity)
                .frame(height: 52)
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accessibilityName(for: tab))
    }

    private var assistantButton: some View {
        Button {
            withAnimation(.snappy(duration: 0.25)) { selection = .assistant }
        } label: {
            ZStack {
                Circle()
                    .fill(Color.white)
                    .frame(width: 58, height: 58)
                    .overlay { Circle().stroke(HSETheme.blue, lineWidth: 2) }
                    .overlay { Circle().stroke(HSETheme.blue.opacity(0.10), lineWidth: 2).padding(-7) }
                    .shadow(color: HSETheme.blue.opacity(0.18), radius: 12, y: 5)
                Image("Voron")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 49, height: 49)
            }
            .frame(maxWidth: .infinity)
            .offset(y: -11)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Помощник Ворон")
    }

    private func accessibilityName(for tab: AppTab) -> String {
        switch tab {
        case .schedule: "Расписание"
        case .search: "Поиск"
        case .assistant: "Помощник"
        case .deadlines: "Дедлайны"
        case .profile: "Профиль"
        }
    }
}
