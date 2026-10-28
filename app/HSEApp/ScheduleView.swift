import SwiftUI

struct ScheduleView: View {
    private let stories = [
        ("Олимпиады", "StoryScience"),
        ("Статдиктант", "StoryStats"),
        ("HSE FEST", "StoryFest"),
        ("Карьера", "StoryCareer")
    ]

    var body: some View {
        ScrollView(showsIndicators: false) {
            VStack(spacing: 22) {
                ScreenHeader(title: "Расписание", actionIcon: "calendar")

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(stories.indices, id: \.self) { index in
                            StoryCard(title: stories[index].0, image: stories[index].1)
                        }
                    }
                    .padding(.horizontal, 9)
                }

                VStack(spacing: 16) {
                    DayCard(day: "СРЕДА, 14 ОКТЯБРЯ")
                    LessonsCard()
                    ExtraDayCard()
                }
                .padding(.horizontal, 16)
            }
            .padding(.top, 0)
            .padding(.bottom, 24)
        }
    }
}

struct ScreenHeader: View {
    let title: String
    var actionIcon: String? = nil

    var body: some View {
        ZStack {
            Text(title)
                .font(.system(size: 22, weight: .bold, design: .rounded))
                .foregroundStyle(HSETheme.ink)
            if let actionIcon {
                HStack {
                    Spacer()
                    Button {} label: {
                        Image(systemName: actionIcon)
                            .font(.system(size: 21, weight: .semibold))
                            .foregroundStyle(HSETheme.blue)
                            .frame(width: 44, height: 44)
                            .background(Color.white.opacity(0.88))
                            .clipShape(Circle())
                            .shadow(color: Color.black.opacity(0.05), radius: 10, y: 4)
                    }
                }
            }
        }
        .padding(.horizontal, 20)
        .frame(height: 62)
    }
}

private struct StoryCard: View {
    let title: String
    let image: String

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Image(image).resizable().scaledToFill()
            LinearGradient(colors: [.clear, .black.opacity(0.72)], startPoint: .center, endPoint: .bottom)
            Text(title.uppercased())
                .font(.system(size: 9.5, weight: .heavy, design: .rounded))
                .lineLimit(2)
            .foregroundStyle(.white)
            .padding(10)
        }
        .frame(width: 88, height: 112)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay { RoundedRectangle(cornerRadius: 12).stroke(HSETheme.blue, lineWidth: 1.5) }
    }
}

private struct ExtraDayCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("ПЯТНИЦА, 16 ОКТЯБРЯ").font(.system(size: 16, weight: .bold))
                Spacer()
                Text("2 пары").font(.caption.weight(.semibold)).foregroundStyle(HSETheme.blue)
            }
            .foregroundStyle(HSETheme.secondary)
            .padding(.bottom, 20)
            LessonRow(number: "1", type: "Лекция", time: "10:30–11:50", title: "Алгоритмы и структуры данных", teacher: "Кузнецов Андрей Сергеевич", room: "R502, Покровский б-р, д.11")
            Divider().padding(.vertical, 18)
            LessonRow(number: "4", type: "Семинар", time: "15:40–17:00", title: "Математический анализ", teacher: "Орлова Мария Игоревна", room: "Онлайн · Zoom")
        }
        .padding(22)
        .hseCard()
    }
}

private struct DayCard: View {
    let day: String
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text(day).font(.system(size: 16, weight: .bold)).foregroundStyle(HSETheme.secondary)
            Text("В этот день пар нет").font(.system(size: 17, weight: .medium)).foregroundStyle(HSETheme.secondary)
        }
        .padding(22)
        .frame(maxWidth: .infinity, alignment: .leading)
        .hseCard()
    }
}

private struct LessonsCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("ЧЕТВЕРГ, 15 ОКТЯБРЯ")
                .font(.system(size: 16, weight: .bold))
                .foregroundStyle(HSETheme.secondary)
                .padding(.bottom, 20)
            LessonRow(number: "2", type: "Лекция", time: "12:10–13:30")
            Divider().padding(.vertical, 18)
            LessonRow(number: "3", type: "Семинар", time: "14:00–15:20")
        }
        .padding(22)
        .hseCard()
    }
}

private struct LessonRow: View {
    let number: String
    let type: String
    let time: String
    var title = "Анализ рынков и конкурентоспособности (рус)"
    var teacher = "Калмычкова Елена Николаевна"
    var room = "R308, Покровский б-р, д.11"

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(number).fontWeight(.bold).frame(width: 28, height: 25).background(HSETheme.blue.opacity(0.08)).clipShape(Capsule())
                Text(type).fontWeight(.semibold)
                Spacer()
                Text(time).fontWeight(.semibold)
            }
            .foregroundStyle(HSETheme.secondary)
            Text(title)
                .font(.system(size: 18, weight: .bold))
                .foregroundStyle(HSETheme.ink)
            Label(teacher, systemImage: "person.crop.circle.fill")
                .font(.subheadline.weight(.medium))
            Text(room)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(HSETheme.secondary)
        }
    }
}
