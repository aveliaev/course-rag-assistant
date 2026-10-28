import SwiftUI

struct ProfileView: View {
    @State private var section = 0
    private let services = [
        ("fork.knife", "Столовые и кафе", Color.cyan),
        ("book.closed.fill", "Зачетная книжка", Color.blue),
        ("chart.bar.fill", "Рейтинг", Color.purple),
        ("building.columns.fill", "Библиотека", Color.mint),
        ("location.fill", "Навигация", Color.orange),
        ("person.text.rectangle.fill", "Читательский билет", Color.teal),
        ("rublesign.circle.fill", "Договоры и платежи", Color.green)
    ]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 18) {
                ScreenHeader(title: "Профиль", actionIcon: "bell")
                profileCard
                Picker("Раздел", selection: $section) {
                    Text("Основное").tag(0)
                    Text("Настройки").tag(1)
                    Text("Ещё").tag(2)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal, 16)

                academicSummary

                VStack(spacing: 0) {
                    ForEach(services.indices, id: \.self) { index in
                        ServiceRow(icon: services[index].0, title: services[index].1, tint: services[index].2)
                        if index < services.count - 1 { Divider().padding(.leading, 68) }
                    }
                }
                .padding(.vertical, 8)
                .hseCard()
                .padding(.horizontal, 16)
            }
            .padding(.top, 8)
            .padding(.bottom, 20)
        }
    }

    private var profileCard: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 6) {
                Text("СТУДЕНТ").font(.caption.bold()).foregroundStyle(HSETheme.blue)
                Text("Веляев Алексей\nВладимирович")
                    .font(.system(size: 23, weight: .bold, design: .rounded))
                    .foregroundStyle(HSETheme.ink)
                Text("Бакалавриат · БПМИ243")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(HSETheme.secondary)
            }
            Spacer()
            ZStack {
                Circle().fill(HSETheme.blue.opacity(0.1)).frame(width: 82, height: 82)
                Image(systemName: "person.fill").font(.system(size: 37)).foregroundStyle(HSETheme.blue)
            }
        }
        .padding(22)
        .hseCard()
        .padding(.horizontal, 16)
    }

    private var academicSummary: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("УЧЁБА").font(.caption.bold()).foregroundStyle(HSETheme.secondary)
            HStack(spacing: 0) {
                ProfileMetric(value: "8,7", label: "Средний балл", tint: .blue)
                Divider().frame(height: 45)
                ProfileMetric(value: "12", label: "Место в рейтинге", tint: .purple)
                Divider().frame(height: 45)
                ProfileMetric(value: "2 курс", label: "БПМИ", tint: .green)
            }
            HStack {
                Label("Студенческий билет", systemImage: "checkmark.seal.fill")
                Spacer()
                Text("до 31.08.2028").foregroundStyle(HSETheme.secondary)
            }
            .font(.caption.weight(.semibold))
        }
        .padding(18)
        .hseCard(cornerRadius: 22)
        .padding(.horizontal, 16)
    }
}

private struct ProfileMetric: View {
    let value: String
    let label: String
    let tint: Color
    var body: some View {
        VStack(spacing: 4) {
            Text(value).font(.headline).foregroundStyle(tint)
            Text(label)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(HSETheme.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct ServiceRow: View {
    let icon: String
    let title: String
    let tint: Color
    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundStyle(.white)
                .frame(width: 44, height: 44)
                .background(tint.gradient)
                .clipShape(Circle())
            Text(title).font(.system(size: 17, weight: .semibold))
            Spacer()
            Image(systemName: "chevron.right").foregroundStyle(HSETheme.secondary.opacity(0.55))
        }
        .padding(.horizontal, 18)
        .frame(height: 65)
    }
}
