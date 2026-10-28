import SwiftUI

struct SearchView: View {
    @State private var query = ""

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 20) {
                ScreenHeader(title: "Поиск")
                HStack(spacing: 12) {
                    Image(systemName: "magnifyingglass").font(.title3)
                    TextField("Поиск по студентам", text: $query)
                }
                .padding(.horizontal, 18)
                .frame(height: 54)
                .background(Color.white.opacity(0.9))
                .clipShape(Capsule())
                .overlay { Capsule().stroke(HSETheme.line) }
                .padding(.horizontal, 16)

                NoticeCard()
                CampusCard()
                ServicesCard()
            }
            .padding(.top, 8)
            .padding(.horizontal, 16)
        }
    }
}

private struct NoticeCard: View {
    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: "sparkles")
                .font(.title2)
                .foregroundStyle(.white)
                .frame(width: 46, height: 46)
                .background(HSETheme.blue.gradient)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            VStack(alignment: .leading, spacing: 4) {
                Text("Сервисы ЕЛК стали удобнее").font(.headline)
                Text("Документы скачиваются сразу, а файлы можно приложить к заявке.")
                    .font(.caption).foregroundStyle(HSETheme.secondary)
            }
        }
        .padding(17)
        .hseCard(cornerRadius: 22)
    }
}

private struct CampusCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Label("Покровский б-р, д.11", systemImage: "mappin.and.ellipse")
                .font(.headline)
            HStack(spacing: 12) {
                QuickService(icon: "door.left.hand.open", title: "Свободные\nаудитории", tint: .cyan)
                QuickService(icon: "fork.knife", title: "Столовые", tint: .orange)
                QuickService(icon: "books.vertical.fill", title: "Библиотека", tint: .mint)
            }
        }
        .padding(20)
        .hseCard()
    }
}

private struct QuickService: View {
    let icon: String
    let title: String
    let tint: Color
    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            Image(systemName: icon).font(.title2).foregroundStyle(tint)
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(HSETheme.ink)
        }
        .padding(14)
        .frame(maxWidth: .infinity, minHeight: 105, alignment: .leading)
        .background(HSETheme.background)
        .clipShape(RoundedRectangle(cornerRadius: 18))
    }
}

private struct ServicesCard: View {
    let rows = [
        ("graduationcap.fill", "Я — студент", "Сервисы для студентов"),
        ("person.text.rectangle.fill", "Центр сервиса «Студент»", "Справки и документы"),
        ("person.3.fill", "ЭКСТРА", "Студенческие сообщества"),
        ("calendar.badge.clock", "Запись на консультацию", "Преподаватели и тьюторы"),
        ("cross.case.fill", "Медицинский кабинет", "Адреса и часы работы"),
        ("sportscourt.fill", "Спорт в Вышке", "Секции и мероприятия")
    ]
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Сервисы").font(.title2.bold())
                Spacer()
                Text("Все").foregroundStyle(HSETheme.blue).fontWeight(.semibold)
            }
            ForEach(rows, id: \.1) { row in
                HStack(spacing: 14) {
                    Image(systemName: row.0)
                        .font(.title3)
                        .foregroundStyle(HSETheme.blue)
                        .frame(width: 48, height: 48)
                        .background(HSETheme.blue.opacity(0.09))
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                    VStack(alignment: .leading, spacing: 3) {
                        Text(row.1).font(.headline)
                        Text(row.2).font(.caption).foregroundStyle(HSETheme.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right").foregroundStyle(HSETheme.secondary.opacity(0.6))
                }
                .padding(.vertical, 8)
            }
        }
        .padding(20)
        .hseCard()
    }
}
