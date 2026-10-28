import SwiftUI

private struct ChatMessage: Identifiable {
    let id = UUID()
    let text: String
    let isMine: Bool
    var attachment: Bool = false
}

struct AssistantView: View {
    let onBack: () -> Void
    @State private var text = ""
    @State private var messages: [ChatMessage] = [
        .init(text: "Мне нужна справка об обучении для визы", isMine: true),
        .init(text: "Помогу оформить. Твоя программа и курс уже заполнены. На каком языке нужна справка?", isMine: false),
        .init(text: "На английском", isMine: true),
        .init(text: "Подготовил заявку. Проверь данные и подтверди отправку.", isMine: false),
        .init(text: "", isMine: false, attachment: true)
    ]

    var body: some View {
        VStack(spacing: 0) {
            assistantHeader
            ScrollViewReader { proxy in
                ScrollView(showsIndicators: false) {
                    LazyVStack(spacing: 14) {
                        ForEach(messages) { message in
                            MessageBubble(message: message)
                                .id(message.id)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 12)
                }
                .onChange(of: messages.count) { _, _ in
                    if let last = messages.last { withAnimation { proxy.scrollTo(last.id, anchor: .bottom) } }
                }
            }
            quickActions
            composer
                .padding(.horizontal, 14)
                .padding(.top, 8)
                .padding(.bottom, 6)
        }
        .padding(.top, 0)
    }

    private var quickActions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                quickButton("Мои пары", icon: "calendar")
                quickButton("Заказать справку", icon: "doc.text")
                quickButton("Найти аудиторию", icon: "location")
                quickButton("Проверить дедлайны", icon: "checklist")
            }
            .padding(.horizontal, 14)
        }
        .frame(height: 40)
    }

    private func quickButton(_ title: String, icon: String) -> some View {
        Button {
            withAnimation(.snappy) {
                messages.append(.init(text: title, isMine: true))
                messages.append(.init(text: quickAnswer(for: title), isMine: false))
            }
        } label: {
            Label(title, systemImage: icon)
                .font(.caption.weight(.semibold))
                .foregroundStyle(HSETheme.blue)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(Color.white.opacity(0.9))
                .clipShape(Capsule())
                .overlay { Capsule().stroke(HSETheme.blue.opacity(0.18)) }
        }
        .buttonStyle(.plain)
    }

    private func quickAnswer(for title: String) -> String {
        switch title {
        case "Мои пары": "Сегодня две пары: лекция в 12:10 и семинар в 14:00, обе в корпусе на Покровском бульваре."
        case "Заказать справку": "Могу подготовить справку об обучении, выписку с оценками или подтверждение статуса студента."
        case "Найти аудиторию": "Напиши номер аудитории — покажу корпус, этаж и кратчайший маршрут."
        default: "Ближайший дедлайн — домашнее задание №4 завтра до 18:00. Ещё четыре задачи запланированы на неделю."
        }
    }

    private var assistantHeader: some View {
        HStack(spacing: 12) {
            Button(action: onBack) {
                Image(systemName: "chevron.left")
                    .font(.system(size: 23, weight: .semibold))
                    .foregroundStyle(HSETheme.blue)
                    .frame(width: 30, height: 56)
            }
            Image("Voron")
                .resizable()
                .scaledToFit()
                .frame(width: 56, height: 56)
                .background(Color.white)
                .clipShape(Circle())
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 7) {
                    Text("ВОРОН").font(.system(size: 21, weight: .heavy, design: .rounded))
                    Circle().fill(Color.green).frame(width: 8, height: 8)
                }
                Text("Помощник студента").font(.subheadline).foregroundStyle(HSETheme.secondary)
            }
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.bottom, 12)
    }

    private var composer: some View {
        HStack(spacing: 10) {
            Button {} label: { Image(systemName: "paperclip").font(.title3).foregroundStyle(HSETheme.secondary) }
            TextField("Напиши сообщение…", text: $text, axis: .vertical)
                .lineLimit(1...3)
                .padding(.horizontal, 14)
                .frame(minHeight: 46)
                .background(HSETheme.background)
                .clipShape(Capsule())
            Button(action: send) {
                Image(systemName: "arrow.up")
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 46, height: 46)
                    .background(HSETheme.blue)
                    .clipShape(Circle())
            }
            .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .opacity(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? 0.45 : 1)
        }
        .padding(8)
        .background(Color.white.opacity(0.9))
        .clipShape(Capsule())
        .shadow(color: Color.black.opacity(0.07), radius: 16, y: 5)
    }

    private func send() {
        let clean = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return }
        withAnimation(.snappy) { messages.append(.init(text: clean, isMine: true)) }
        text = ""
    }
}

private struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            if message.isMine { Spacer(minLength: 52) }
            if !message.isMine {
                Image("Voron")
                    .resizable().scaledToFit().frame(width: 34, height: 34)
                    .background(Color.white).clipShape(Circle())
            }
            Group {
                if message.attachment { RequestCard() }
                else {
                    Text(message.text)
                        .font(.system(size: 16, weight: .regular))
                        .foregroundStyle(message.isMine ? Color.white : HSETheme.ink)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                        .background(message.isMine ? HSETheme.blue : Color.white.opacity(0.9))
                        .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
                        .shadow(color: message.isMine ? .clear : Color.black.opacity(0.035), radius: 8, y: 3)
                }
            }
            if !message.isMine { Spacer(minLength: 36) }
        }
        .frame(maxWidth: .infinity)
    }
}

private struct RequestCard: View {
    @State private var confirmed = false
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("СПРАВКА ОБ ОБУЧЕНИИ", systemImage: "doc.text.fill")
                .font(.system(size: 14, weight: .bold))
            Divider()
            HStack { Text("Язык:").foregroundStyle(HSETheme.secondary); Spacer(); Text("английский") }
            HStack { Text("Цель:").foregroundStyle(HSETheme.secondary); Spacer(); Text("виза") }
            Button {
                withAnimation(.snappy) { confirmed.toggle() }
            } label: {
                Label(confirmed ? "Заявка подтверждена" : "Подтвердить", systemImage: confirmed ? "checkmark.circle.fill" : "paperplane.fill")
                    .font(.headline)
                    .frame(maxWidth: .infinity)
                    .frame(height: 48)
                    .foregroundStyle(.white)
                    .background(confirmed ? Color.green : HSETheme.blue)
                    .clipShape(RoundedRectangle(cornerRadius: 15))
            }
        }
        .padding(16)
        .frame(maxWidth: 292)
        .background(Color.white.opacity(0.95))
        .clipShape(RoundedRectangle(cornerRadius: 22))
    }
}
