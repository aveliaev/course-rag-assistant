import SwiftUI

struct DeadlinesView: View {
    @State private var completed: Set<Int> = []
    private let tasks = [
        ("Оплатить подписку Claude", "Сегодня, до 23:59", "Личное", Color.orange),
        ("Домашнее задание №4", "Завтра, до 18:00", "Алгоритмы", Color.blue),
        ("Загрузить эссе в LMS", "19 октября, до 23:59", "Экономика", Color.purple),
        ("Регистрация на майнор", "22 октября, до 17:00", "Учёба", Color.green),
        ("Командная презентация", "26 октября, 14:00", "Проект", Color.pink)
    ]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 18) {
                ScreenHeader(title: "Дедлайны", actionIcon: "plus")
                summary
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("АКТИВНЫЕ ДЕДЛАЙНЫ").font(.caption.bold()).foregroundStyle(HSETheme.secondary)
                        Spacer()
                        Text("\(tasks.count - completed.count) осталось").font(.caption.weight(.semibold)).foregroundStyle(HSETheme.blue)
                    }
                    ForEach(tasks.indices, id: \.self) { index in
                        deadlineRow(index)
                        if index < tasks.count - 1 { Divider().padding(.leading, 44) }
                    }
                }
                .padding(20)
                .hseCard()
            }
            .padding(.top, 8)
            .padding(.horizontal, 16)
        }
    }

    private var summary: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text("На этой неделе").font(.caption).foregroundStyle(HSETheme.secondary)
                Text("4 задачи").font(.title3.bold())
            }
            Spacer()
            ZStack {
                Circle().stroke(HSETheme.line, lineWidth: 7)
                Circle().trim(from: 0, to: 0.4).stroke(HSETheme.blue, style: StrokeStyle(lineWidth: 7, lineCap: .round)).rotationEffect(.degrees(-90))
                Text("40%").font(.caption.bold()).foregroundStyle(HSETheme.blue)
            }
            .frame(width: 54, height: 54)
        }
        .padding(18)
        .hseCard(cornerRadius: 22)
    }

    private func deadlineRow(_ index: Int) -> some View {
        Button {
            withAnimation(.snappy) {
                if completed.contains(index) { completed.remove(index) } else { completed.insert(index) }
            }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: completed.contains(index) ? "checkmark.circle.fill" : "circle")
                    .font(.title2).foregroundStyle(completed.contains(index) ? Color.green : HSETheme.secondary)
                VStack(alignment: .leading, spacing: 4) {
                    Text(tasks[index].0).font(.subheadline.weight(.semibold)).strikethrough(completed.contains(index))
                    Text(tasks[index].1).font(.caption).foregroundStyle(HSETheme.secondary)
                }
                Spacer()
                Text(tasks[index].2)
                    .font(.caption2.weight(.bold)).foregroundStyle(tasks[index].3)
                    .padding(.horizontal, 8).padding(.vertical, 5)
                    .background(tasks[index].3.opacity(0.1)).clipShape(Capsule())
            }
            .padding(.vertical, 9)
        }
        .buttonStyle(.plain)
    }
}
