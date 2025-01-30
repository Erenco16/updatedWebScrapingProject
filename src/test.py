import unittest
from bs4 import BeautifulSoup

# ✅ Define test URLs
TEST_RESPONSES = ['''<div>
<div><div id="ViewObjectJson" data-value="{&quot;addToCartButtonUrl&quot;:null,&quot;configurationAttributeErrorMessages&quot;:{&quot;UNDEFINED&quot;:&quot;Geçersiz değer&quot;,&quot;LT&quot;:&quot;Değer {0} değerinden küçük olmalıdır&quot;,&quot;LE&quot;:&quot;Değer {0} değerinden küçük veya ona eşit olmalıdır&quot;,&quot;SCALE&quot;:&quot;Sadece {0} ondalık sayılara izin verilir&quot;,&quot;EQ&quot;:&quot;Değer yalnızca {0} olabilir&quot;,&quot;GT&quot;:&quot;Değer {0} değerinden büyük olmalıdır&quot;,&quot;EMPTY&quot;:&quot;Lütfen bir değer girin&quot;,&quot;GE&quot;:&quot;Değer {0} değerinden büyük veya eşit olmalıdır&quot;},&quot;SUBSTITUTION&quot;:false,&quot;SUBSTITUTION_LINK&quot;:false,&quot;RUNNING_OUT_NOTE&quot;:false,&quot;isArticle&quot;:true,&quot;messages&quot;:{&quot;haefele.product.note.addToCart.substitution&quot;:&quot;Değiştirilen Ürün alışveriş sepetine eklenecektir.&quot;,&quot;haefele.product.note.addToCart.config.attributes&quot;:&quot;Yapılandırma henüz tamamlanmadı. Lütfen gerekli tüm özellikleri tanımlayın.&quot;,&quot;haefele.product.add.to.cart&quot;:&quot;Sepete ekle&quot;,&quot;haefele.product.note.addToCart.reduced&quot;:&quot;Bu öğe mevcut miktara düşürüldü.&quot;,&quot;haefele.product.add.to.cart.tip&quot;:&quot;Lütfen bir ürün seçin&quot;,&quot;haefele.product.state.NOT_AVAILABLE&quot;:&quot;Bu ürün artık mevcut değil.&quot;},&quot;availabilityInfoColor&quot;:&quot;&quot;,&quot;errors&quot;:[],&quot;addToCartButtonText&quot;:null,&quot;FOLLOWUP&quot;:false}"></div></div><table>
<tbody><tr id="productPriceInformation">
<td></td><td id="" class="pricedisplay CUSTOMER_PRICE_Display">
<p class="price"><span class="price">1.255,36 TL</span>
<span class="perUnit">#  Adet (ADT)
</span><input type="hidden" class="exclude-product-to-cart" id="ExcludeProductToCart" value="false">
</p>
</td><td id="" class="pricedisplay SALES_PRICE_Display hidden">
<p class="price"><span class="price">1.883,04 TL</span>
<span class="perUnit">#  Adet (ADT)
</span><input type="hidden" class="exclude-product-to-cart" id="ExcludeProductToCart" value="false">
</p>
</td><td id="" class="pricedisplay UVPE_Display hidden">
<p class="price"><span class="price">1.757,50 TL</span>
<span class="perUnit">#  Adet (ADT)
</span><input type="hidden" class="exclude-product-to-cart" id="ExcludeProductToCart" value="false">
</p>
</td></tr>
</tbody></table> 
<table><tbody><tr id="productRequestedPackagesInformation" class="detailViewComp">
<td class="u-display-block"><div class="packUnitTitle">Paket birim miktarları</div>
<table class="RequestedPackageTable productDataTable table table-bordered">
<tbody><tr class="requestedPackagesHeading available-units-header"> 
<td class="qty-label-header">Miktar (ADT)</td>
<td class="pu-label-header">Paket birimi (PB)</td>
<td class="stock-label-header">Stok durumu</td></tr><tr class="values-tr"> 
<td class="qty-available">83</td>
<td class="packaging-available">83 x Ambalaj birimi 1</td>
<td class="requestedPackageStatus">
<span class="availability-flag" style="color:#339C76">stokta mevcut 
</span>
</td></tr>
<tr class="values-tr"> 
<td class="qty-available">229917</td>
<td class="packaging-available">229917 x Ambalaj birimi 1</td>
<td class="requestedPackageStatus">
<span class="availability-flag" style="color:#FFA50A">bir ay içinde 
</span>
</td></tr></tbody></table></td>
</tr></tbody></table>
<table><tbody><tr id="productAvailablePackagesInformation" class="detailViewComp"><td class="u-display-block"></td>
</tr></tbody></table><table border="1">
<tbody><tr>
<td id="productAvailabilityInformation"> 
<p class="hfl-product--availability--info">
<span class="availability-flag" style="color:#FFA50A">bir ay içinde</span> 
<span class="top-products-availability-flag hidden" data-availability-status-color="#FFA50A" data-availability-status-message="bir ay içinde">
</span>
<input type="hidden" class="specialstock-status-message" id="SpecialStockStatus" value="OK"> 
</p>
</td>
</tr>
</tbody></table>
<table>
<tbody><tr>
<td id="synchronizationAjaxToken" data-synchronization-token="1">
</td>
<td id="articleNotAvailable" data-article-not-available="false">
</td><td id="confirmedQuantityResponse" data-confirmed-quantity="230.000" data-total-price="288.732.133,00 TL" data-total-price-nocrr="288.732.133,00">
</td></tr>
</tbody></table><table>
<tbody><tr>
<td id="substitutionArticles">
<div id="SubstitutionArticlesContainer"> 
<script></script></div>
</td>
</tr>
</tbody></table> 
<table>
<tbody><tr>
<td>
<div id="addToWishlistLinkContainer">
<div class="warningFlyoutWrapper addToWishlistWarningFlyoutWrapper add-to-wisth-list">
<button class="shoppingCartOption is-link-view hflLink

ajaxLayerSubmit" data-method="POST" data-initialize-forms="true" type="submit" name="AddToWishlist" data-testid="AddToWishlist" container="#wishlistContainer">
<span class="bookmark-label">Alışveriş listesine ekle</span>
<svg width="23" height="23" viewBox="0 0 64 64" class="svg-icons"><use xlink:href="#icn-097-2-bookmark-add"></use></svg>
</button> 
</div>
</div></td>
</tr>
</tbody></table>
<table>
<tbody><tr>
<td>
<div id="productInfoConfigurationAttributes"></div>
<div id="productInfoConfigurationFirstStepHeader">
<div class="configurationStep collapse__heading firstStep">Ürün özelliklerini seçin</div>
</div>
</td>
</tr>
</tbody></table> 
</div>''']

# Assuming functions for HTML parsing to test their usage
class TestHtmlParsing(unittest.TestCase):
    def setUp(self):
        """Define initial test data for all tests."""
        self.test_response_html = TEST_RESPONSES[0]
        self.soup = BeautifulSoup(self.test_response_html, 'html.parser')

    def test_price_extraction(self):
        """Test price extraction from the HTML content."""
        price_elements = self.soup.select('.pricedisplay .price')
        prices = [p.text.strip() for p in price_elements]

        # Check if prices are extracted correctly
        expected_prices = ['1.255,36 TL', '1.883,04 TL', '1.757,50 TL']
        self.assertEqual(prices, expected_prices)

    def test_stock_availability(self):
        """Test stock availability extraction."""
        stock_status = self.soup.select('.availability-flag')
        statuses = [status.text.strip() for status in stock_status]

        # Check extracted availability messages
        expected_statuses = ['stokta mevcut', 'bir ay içinde', 'bir ay içinde']
        self.assertTrue(all(status in statuses for status in expected_statuses))

    def test_requested_packages_info(self):
        """Test extraction of requested package information."""
        requested_packages = self.soup.select('#productRequestedPackagesInformation .values-tr .qty-available')
        package_quantities = [package.text.strip() for package in requested_packages]

        # Expected quantities in the test response
        expected_quantities = ['83', '229917']
        self.assertEqual(package_quantities, expected_quantities)

    def test_total_price_extraction(self):
        """Test extracting total price from hidden elements."""
        total_price_element = self.soup.select_one('#confirmedQuantityResponse')
        total_price = total_price_element.attrs.get('data-total-price', None)

        # Assert total price matches the expected output
        expected_total_price = '288.732.133,00 TL'
        self.assertEqual(total_price, expected_total_price)

    def test_product_messages(self):
        """Test product-specific informational messages."""
        messages_data = self.soup.select_one('#ViewObjectJson')
        if messages_data:
            data_value = messages_data.get('data-value', None)
            messages = 'haefele.product.add.to.cart' in data_value

            # Check if a specific message exists
            self.assertTrue(messages)
        else:
            self.fail("Product messages not found in the response.")


if __name__ == '__main__':
    unittest.main()
