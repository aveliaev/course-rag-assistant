import SwiftUI

enum HSETheme {
    static let blue = Color(red: 0.03, green: 0.38, blue: 0.95)
    static let ink = Color(red: 0.06, green: 0.08, blue: 0.13)
    static let secondary = Color(red: 0.41, green: 0.46, blue: 0.60)
    static let surface = Color.white.opacity(0.82)
    static let line = Color(red: 0.88, green: 0.90, blue: 0.94)
    static let background = Color(red: 0.96, green: 0.97, blue: 0.99)
}

extension View {
    func hseCard(cornerRadius: CGFloat = 28) -> some View {
        self
            .background(HSETheme.surface)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.9), lineWidth: 1)
            }
            .shadow(color: Color.black.opacity(0.045), radius: 18, y: 7)
    }
}
